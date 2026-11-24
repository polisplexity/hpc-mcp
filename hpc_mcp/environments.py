"""Manage operator-approved environments on the configured SSH target."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile
from uuid import UUID

from . import client, environment_worker, r_worker, remote_storage, ssh_jobs, worker


ENV_ROOT = "POLISPLEXITY_HPC_SSH_ENV_ROOT"
DATA_ROOT = "POLISPLEXITY_HPC_SSH_DATA_ROOT"
DOWNLOAD_ROOT = "POLISPLEXITY_HPC_DOWNLOAD_ROOT"
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


def remote_source(action, **payload):
    body = worker.canonical({"action": action, "root": os.getenv(ENV_ROOT), "data_root": os.getenv(DATA_ROOT), **payload})
    modules = (worker, environment_worker, r_worker, remote_storage, ssh_jobs)
    source = b"\n".join(Path(module.__file__).read_bytes() for module in modules)
    return source + (
        "\ndef storage_factory(path):\n"
        "    if not path:\n        raise ValueError('Configure private SSH data storage')\n"
        "    return RemoteStorage(private_root(path), ARTIFACT_REFERENCE, MAX_REFERENCED_OUTPUT_BYTES)\n"
        "runtime = RRuntime(MAX_FILE_BYTES, MAX_REFERENCED_OUTPUT_BYTES)\n"
        "def jobs_factory(path):\n"
        "    return SSHJobs(runtime, storage_factory(path), stage_job, job_receipt, atomic_json)\n"
        f"environment_dispatch({body!r}, execute, execute_native, runtime, storage_factory, jobs_factory)\n"
    ).encode("ascii")


def request(action, timeout, **payload):
    command = client.ssh_python(os.getenv(client.SSH_ALIAS))
    source = remote_source(action, **payload)
    try:
        result = subprocess.run(command, input=source, capture_output=True, check=True, timeout=timeout)
        envelope = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError("The SSH environment worker returned no verified response") from None
    if "error" in envelope:
        raise RuntimeError(envelope["error"])
    return envelope["result"]


def reference_checksum(reference):
    checksum = reference.removeprefix(worker.ARTIFACT_REFERENCE)
    if checksum == reference or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ValueError("Use a valid HPC artifact reference")
    return checksum


def verify_artifact(reference):
    checksum = reference_checksum(reference)
    result = request("verify_artifact", 30, reference=reference)
    if result["reference"] != reference or result["sha256"] != checksum or result["verified"] is not True:
        raise RuntimeError("The worker returned a different artifact")
    return result


def fetch_artifact(reference):
    checksum = reference_checksum(reference)
    directory = os.getenv(DOWNLOAD_ROOT)
    if not directory:
        raise ValueError("Configure a local HPC download directory")
    command = client.ssh_python(os.getenv(client.SSH_ALIAS))
    try:
        root = Path(directory).resolve(strict=True)
        with NamedTemporaryFile(dir=root, prefix=".fetch-") as temporary:
            subprocess.run(command, input=remote_source("fetch_artifact", reference=reference),
                           stdout=temporary, stderr=subprocess.PIPE, check=True, timeout=45)
            temporary.seek(0)
            size, actual = remote_storage.hash_stream(temporary, worker.MAX_REFERENCED_OUTPUT_BYTES)
            if actual != checksum:
                raise ValueError("The downloaded bytes failed SHA-256 verification")
            remote_storage.publish_blob(root, temporary, size, checksum)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Unable to retrieve and save the referenced SSH artifact") from None
    return {"reference": reference, "filename": checksum, "size_bytes": size, "sha256": checksum, "verified": True}


def probe(workspace=None):
    locks = {}
    if workspace is not None:
        for path in sorted((workspace / "environments").glob("*.json")):
            locks[path.stem] = environment_lock(workspace, path.stem)
    cpus, memory, wall_time = worker.PROFILES[PROFILE]
    ceilings = {"jobs_per_batch": MAX_BATCH_JOBS, "parallel_jobs_per_batch": 1,
                "cpus_per_job": cpus, "memory_mib_per_job": memory,
                "wall_time_seconds_per_job": wall_time, "bytes_per_file": worker.MAX_FILE_BYTES,
                "referenced_output_bytes_per_file": worker.MAX_REFERENCED_OUTPUT_BYTES}
    return {**request("probe", 30, locks=locks), "job_limits": ceilings}


def prepare(workspace, name):
    lock = environment_lock(workspace, name)
    return request("prepare", 215 if "r_version" in lock else 120, name=name, lock=lock)


def ssh_submit(workspace, name, manifest, request_id, expected_environment_id):
    job_id = str(UUID(request_id))
    lock = environment_lock(workspace, name)
    if "r_version" not in lock or not re.fullmatch(r"[a-f0-9]{64}", expected_environment_id):
        raise ValueError("Use an approved Docker R environment and its prepared ID")
    job = client.prepare(workspace, manifest, R_PROFILE)
    result = request("ssh_submit", 50, name=name, job_id=job_id, job=job, lock=lock,
                     expected_environment_id=expected_environment_id)
    if (result["job_id"] != job_id or result["environment_id"] != expected_environment_id
            or result["manifest_sha256"] != client.describe(job)["manifest_sha256"]):
        raise RuntimeError("The SSH worker returned a different job")
    if "receipt" in result:
        client.verify_receipt(result["receipt"], job)
    return result


def ssh_status(request_id):
    job_id = str(UUID(request_id))
    result = request("ssh_status", 40, job_id=job_id)
    if result["job_id"] != job_id:
        raise RuntimeError("The SSH worker returned a different job")
    return result


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
            if "base64" in artifact and artifact["path"].endswith(".json") and artifact["size_bytes"] <= 4096:
                try:
                    json_outputs[artifact["path"]] = json.loads(base64.b64decode(artifact["base64"]))
                except (ValueError, RecursionError):
                    pass
        result = {"manifest": manifest, "receipt": receipt, "json_outputs": json_outputs}
        remote_inputs = [item for item in job["manifest"]["inputs"] if "source" in item]
        if remote_inputs:
            result["remote_inputs"] = remote_inputs
        results.append(result)
    return {**batch, "results": results}
