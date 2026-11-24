"""Manage operator-approved Python environments on the configured SSH target."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess

from . import client, environment_worker, worker


ENV_ROOT = "POLISPLEXITY_HPC_SSH_ENV_ROOT"
MAX_BATCH_JOBS = 4


def environment_lock(workspace, name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", name):
        raise ValueError("Choose an approved environment name")
    try:
        lock = json.loads(worker.read_file(workspace, f"environments/{name}.json"))
    except FileNotFoundError:
        raise ValueError("The environment is not approved in this workspace") from None
    worker.require_keys(lock, {"packages"})
    packages = lock["packages"]
    if not isinstance(packages, list) or not 1 <= len(packages) <= 24:
        raise ValueError("Lock between one and 24 wheel packages")
    names = set()
    for package in packages:
        worker.require_keys(package, {"name", "version", "sha256"})
        distribution = package["name"]
        if not isinstance(distribution, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", distribution):
            raise ValueError("Use normalized lowercase distribution names")
        if distribution in names or distribution in {"pip", "setuptools", "wheel"}:
            raise ValueError("Lock unique application packages")
        names.add(distribution)
        version = package["version"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9][a-z0-9.+!]{0,39}", version):
            raise ValueError("Lock an exact distribution version")
        hashes = package["sha256"]
        if not isinstance(hashes, list) or not 1 <= len(hashes) <= 16 or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) for value in hashes
        ):
            raise ValueError("Lock at least one approved wheel SHA-256 per package")
    return lock


def request(action, timeout, **payload):
    command = client.ssh_python(os.getenv(client.SSH_ALIAS))
    body = worker.canonical({"action": action, "root": os.getenv(ENV_ROOT), **payload})
    source = Path(worker.__file__).read_bytes() + b"\n" + Path(environment_worker.__file__).read_bytes()
    source += f"\nenvironment_dispatch({body!r}, execute)\n".encode("ascii")
    try:
        result = subprocess.run(command, input=source, capture_output=True, check=True, timeout=timeout)
        envelope = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError("The SSH environment worker returned no verified response") from None
    if "error" in envelope:
        raise RuntimeError(envelope["error"])
    return envelope["result"]


def probe(workspace=None):
    locks = {}
    if workspace is not None:
        for path in sorted((workspace / "environments").glob("*.json")):
            locks[path.stem] = environment_lock(workspace, path.stem)
    return request("probe", 30, locks=locks)


def prepare(workspace, name):
    return request("prepare", 120, name=name, lock=environment_lock(workspace, name))


def run_batch(workspace, name, manifests):
    if not 1 <= len(manifests) <= MAX_BATCH_JOBS or len(set(manifests)) != len(manifests):
        raise ValueError("Supply one to four distinct trusted job manifests")
    lock = environment_lock(workspace, name)
    jobs = [client.prepare(workspace, manifest, "ssh") for manifest in manifests]
    timeout = sum(job["manifest"]["resources"]["wall_time_seconds"] for job in jobs) + 35
    batch = request("batch", timeout, name=name, lock=lock, jobs=jobs)
    for manifest, receipt, job in zip(manifests, batch["receipts"], jobs, strict=True):
        client.verify_receipt(receipt, job)
        receipt["manifest"] = manifest
        receipt["json_outputs"] = {}
        for artifact in receipt["artifacts"]:
            if artifact["path"].endswith(".json") and artifact["size_bytes"] <= 4096:
                try:
                    receipt["json_outputs"][artifact["path"]] = json.loads(base64.b64decode(artifact["base64"]))
                except (ValueError, RecursionError):
                    pass
    return batch
