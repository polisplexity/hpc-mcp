"""Manage operator-approved environments on the configured SSH target."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess

from . import client, environment_worker, r_worker, worker


ENV_ROOT = "POLISPLEXITY_HPC_SSH_ENV_ROOT"
MAX_BATCH_JOBS = 4
PROFILE = "ssh-env"
R_PROFILE = "ssh-r"


def environment_lock(workspace, name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", name):
        raise ValueError("Choose an approved environment name")
    try:
        lock = json.loads(worker.read_file(workspace, f"environments/{name}.json"))
    except FileNotFoundError:
        raise ValueError("The environment is not approved in this workspace") from None
    if isinstance(lock, dict) and "r_version" in lock:
        worker.require_keys(lock, {"r_version", "image", "platform"})
        if not isinstance(lock["r_version"], str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", lock["r_version"]):
            raise ValueError("Specify the exact approved R version")
        if not isinstance(lock["image"], str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?(?:/[a-z0-9][a-z0-9._-]*)+@sha256:[a-f0-9]{64}", lock["image"]
        ):
            raise ValueError("Lock the approved R image by registry and digest")
        if lock["platform"] not in ("linux/amd64", "linux/arm64"):
            raise ValueError("Lock a supported Linux image platform")
        return lock
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
    source = b"\n".join(Path(module.__file__).read_bytes() for module in (worker, environment_worker, r_worker))
    source += f"\nenvironment_dispatch({body!r}, execute, execute_native, RRuntime(MAX_FILE_BYTES))\n".encode("ascii")
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
    cpus, memory, wall_time = worker.PROFILES[PROFILE]
    ceilings = {"jobs_per_batch": MAX_BATCH_JOBS, "parallel_jobs_per_batch": 1,
                "cpus_per_job": cpus, "memory_mib_per_job": memory,
                "wall_time_seconds_per_job": wall_time, "bytes_per_file": worker.MAX_FILE_BYTES}
    return {**request("probe", 30, locks=locks), "job_limits": ceilings}


def prepare(workspace, name):
    lock = environment_lock(workspace, name)
    return request("prepare", 215 if "r_version" in lock else 120, name=name, lock=lock)


def run_batch(workspace, name, manifests, expected_environment_id=None):
    if not 1 <= len(manifests) <= MAX_BATCH_JOBS or len(set(manifests)) != len(manifests):
        raise ValueError("Supply one to four distinct trusted job manifests")
    lock = environment_lock(workspace, name)
    profile = R_PROFILE if "r_version" in lock else PROFILE
    if profile == R_PROFILE and not (expected_environment_id and re.fullmatch(r"[a-f0-9]{64}", expected_environment_id)):
        raise ValueError("Supply the environment ID returned when preparing the R environment")
    jobs = [client.prepare(workspace, manifest, profile) for manifest in manifests]
    launch_overhead = 40 * len(jobs) if profile == R_PROFILE else 0
    timeout = sum(job["manifest"]["resources"]["wall_time_seconds"] for job in jobs) + 35 + launch_overhead
    batch = request("batch", timeout, name=name, lock=lock, jobs=jobs, profile=profile,
                    expected_environment_id=expected_environment_id)
    results = []
    for manifest, receipt, job in zip(manifests, batch.pop("receipts"), jobs, strict=True):
        client.verify_receipt(receipt, job)
        json_outputs = {}
        for artifact in receipt["artifacts"]:
            if artifact["path"].endswith(".json") and artifact["size_bytes"] <= 4096:
                try:
                    json_outputs[artifact["path"]] = json.loads(base64.b64decode(artifact["base64"]))
                except (ValueError, RecursionError):
                    pass
        results.append({"manifest": manifest, "receipt": receipt, "json_outputs": json_outputs})
    return {**batch, "results": results}
