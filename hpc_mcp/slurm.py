"""Queue portable Python jobs on a configured Slurm login host."""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from uuid import UUID

from . import worker
from .client import describe, verify_receipt
from .worker import atomic_json


STATE_ROOT = "POLISPLEXITY_HPC_SLURM_STATE"
PARTITION = "POLISPLEXITY_HPC_SLURM_PARTITION"
ACCOUNT = "POLISPLEXITY_HPC_SLURM_ACCOUNT"
PYTHON = "POLISPLEXITY_HPC_SLURM_PYTHON"
TERMINAL = {
    "BOOT_FAIL", "CANCELLED", "COMPLETED", "DEADLINE", "FAILED", "NODE_FAIL",
    "OUT_OF_MEMORY", "PREEMPTED", "REVOKED", "SPECIAL_EXIT", "TIMEOUT",
}
RUNNER_TAIL = b"""
package = json.loads(Path("package.json").read_bytes())
job_id = Path.cwd().name
receipt = execute(package["manifest"], package["files"], "slurm", job_id)
with open("receipt.tmp", "wb") as stream:
    stream.write(canonical(receipt))
    stream.flush()
    os.fsync(stream.fileno())
os.replace("receipt.tmp", "receipt.json")
exit_code = receipt["exit_code"]
raise SystemExit(exit_code if exit_code >= 0 else 128 - exit_code)
"""


def native(command, *, data=None):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("SBATCH_", "SCANCEL_")) and key != "SLURM_CLUSTERS"}
    env["LC_ALL"] = "C"
    return subprocess.run(
        command, input=data, capture_output=True, timeout=15,
        env=env,
    )


def observed(command):
    try:
        response = native(command)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if response.returncode:
        return None
    return [line.split("|") for line in response.stdout.decode("utf-8").splitlines() if line]


def read_json(path):
    return json.loads(path.read_bytes())


class SlurmProfile:
    def __init__(self, location, partition, account=None, python="/usr/bin/python3"):
        if sys.platform != "linux":
            raise ValueError("Run the Slurm profile on a Linux login host")
        if not location or not partition:
            raise ValueError("Configure a private Slurm state directory and an authorized partition")
        for name in (partition, account):
            if name is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise ValueError("Invalid Slurm partition or account in the local profile")
        self.partition = partition
        self.account = account
        if not Path(python).is_absolute() or "\n" in python or "\0" in python:
            raise ValueError("Use an absolute Slurm Python interpreter path")
        self.python = python
        self.batch_script = (
            f"#!/bin/sh\nset -eu\numask 077\nexec {shlex.quote(python)} -I -B runner.py\n"
        ).encode()
        location = Path(location)
        if not location.is_absolute():
            raise ValueError("Use an absolute Slurm state directory path")
        location.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.location = location.resolve(strict=True)
        stat = self.location.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError("The Slurm state directory must be private and owned by the executing user")

    @classmethod
    def configured(cls):
        return cls(os.getenv(STATE_ROOT), os.getenv(PARTITION), os.getenv(ACCOUNT),
                   os.getenv(PYTHON, "/usr/bin/python3"))

    def preflight(self):
        rows = observed(["sinfo", "--noheader", "--format=%P|%a"])
        if rows is None:
            raise RuntimeError("Slurm partition discovery failed")
        partitions = {name.rstrip("*"): state for name, state in rows}
        try:
            version = native(["sbatch", "--version"])
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("Slurm submit client is unavailable") from None
        if version.returncode:
            raise RuntimeError("Slurm submit client is unavailable")
        return {
            "version": version.stdout.decode("utf-8").strip(),
            "partition_visible": self.partition in partitions,
            "partition_state": partitions.get(self.partition),
            "account_configured": bool(self.account),
        }

    def submission_args(self, directory, resources):
        args = [
            "sbatch", "--parsable", "--no-requeue", "--export=NIL", "--nodes=1", "--ntasks=1",
            f"--job-name=polishpc-{UUID(directory.name).hex}", f"--partition={self.partition}",
            f"--cpus-per-task={resources['cpus']}", f"--mem={resources['memory_mib']}M",
            f"--time={max(1, (resources['wall_time_seconds'] + 59) // 60)}",
            f"--chdir={directory}", "--output=slurm.out", "--error=slurm.err",
        ]
        if self.account:
            args.append(f"--account={self.account}")
        return args

    def submit(self, package, request_id):
        import fcntl

        job_id = str(UUID(request_id))
        prepared = describe(package)
        if prepared["profile"] != "slurm":
            raise ValueError("Expected a prepared Slurm workload")
        directory = self.location / job_id
        directory.mkdir(mode=0o700, exist_ok=True)
        with (directory / "dispatch.lock").open("ab") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            intent_path = directory / "intent.json"
            if intent_path.exists():
                intent = read_json(intent_path)
                if intent["manifest_sha256"] != prepared["manifest_sha256"]:
                    raise ValueError("This request ID is bound to a different manifest")
                return self.status(job_id)
            (directory / "runner.py").write_bytes(Path(worker.__file__).read_bytes() + RUNNER_TAIL)
            atomic_json(directory / "package.json", package)
            atomic_json(intent_path, {
                "manifest_sha256": prepared["manifest_sha256"],
                "created_at": worker.timestamp(),
                "search_start": (date.today() - timedelta(days=1)).isoformat(),
            })
            try:
                result = native(
                    self.submission_args(directory, prepared["resources"]), data=self.batch_script,
                )
            except (OSError, subprocess.TimeoutExpired):
                return self.status(job_id)
            output = result.stdout.decode("utf-8").strip()
            if result.returncode == 0 and re.fullmatch(r"[1-9][0-9]*(;[A-Za-z0-9_.-]+)?", output):
                native_id = output.split(";")[0]
                atomic_json(directory / "ack.json", {"native_id": native_id})
                return {"job_id": job_id, "native_id": native_id, "state": "submitted"}
            return self.status(job_id)

    def cancel(self, request_id):
        import fcntl

        job_id = str(UUID(request_id))
        directory = self.location / job_id
        if not (directory / "intent.json").is_file():
            raise ValueError("Unknown Slurm request ID in the local state directory")
        with (directory / "dispatch.lock").open("ab") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            snapshot = self.status(job_id)
            if snapshot["state"] != "active" or snapshot["native_state"] == "COMPLETING":
                return snapshot
            if (directory / "cancel-ack.json").is_file():
                return snapshot
            native_id = snapshot["native_id"]
            if not re.fullmatch(r"[1-9][0-9]*", native_id):
                raise RuntimeError("Slurm did not report a single numeric allocation")
            job_name = f"polishpc-{UUID(job_id).hex}"
            identity = [f"--user={os.getuid()}", f"--name={job_name}", f"--partition={self.partition}"]
            queued = observed(["squeue", "--noheader", *identity, "--format=%i|%j"])
            if queued != [[native_id, job_name]]:
                return self.status(job_id)
            try:
                reply = native(["scancel", "--ctld", "--quiet", *identity, native_id])
            except subprocess.TimeoutExpired:
                return self.status(job_id)
            except OSError:
                raise RuntimeError("Slurm cancellation client is unavailable") from None
            if reply.returncode == 0:
                atomic_json(directory / "cancel-ack.json", {"native_id": native_id})
            latest = self.status(job_id)
            if reply.returncode and latest["state"] == "active":
                raise RuntimeError("Slurm did not acknowledge cancellation of the allocation")
            return latest

    def status(self, request_id):
        job_id = str(UUID(request_id))
        directory = self.location / job_id
        intent_path = directory / "intent.json"
        if not intent_path.is_file():
            raise ValueError("Unknown Slurm request ID in the local state directory")
        intent = read_json(intent_path)
        job_name = f"polishpc-{UUID(job_id).hex}"
        identity = [f"--user={os.getuid()}", f"--name={job_name}"]
        queue = observed(["squeue", "--noheader", *identity, "--format=%i|%j|%T"])
        accounting = observed([
            "sacct", "--noheader", "--parsable2", "--allocations", *identity,
            f"--starttime={intent['search_start']}",
            "--format=JobIDRaw,JobName%80,State%40,ExitCode,Submit,Start,End,ElapsedRaw",
        ])
        ack_path = directory / "ack.json"
        native_id = read_json(ack_path)["native_id"] if ack_path.is_file() else None
        queued = {row[0]: row[2] for row in queue or [] if len(row) == 3 and row[1] == job_name}
        accounted = {row[0]: row[2:] for row in accounting or [] if len(row) == 8 and row[1] == job_name}
        ids = set(queued) | set(accounted)
        if native_id:
            ids.add(native_id)
        snapshot = {
            "job_id": job_id,
            "state": "unknown",
            "native_id": native_id,
            "sources": {"squeue": queue is not None, "sacct": accounting is not None},
        }
        if len(ids) != 1:
            return snapshot
        snapshot["native_id"] = native_id = next(iter(ids))
        if native_id in queued:
            return {**snapshot, "state": "active", "native_state": queued[native_id]}
        if native_id not in accounted:
            return snapshot
        state, exit_code, submitted, started, ended, duration = accounted[native_id]
        state = state.split(" ", 1)[0].rstrip("+")
        snapshot.update(native_state=state, native_exit_code=exit_code, timing={
            "submitted": submitted, "started": started, "ended": ended,
            "elapsed_seconds": int(duration) if duration.isdigit() else None,
        })
        if state not in TERMINAL:
            return {**snapshot, "state": "active"}
        if state == "CANCELLED":
            return {**snapshot, "state": "cancelled"}
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            return {**snapshot, "state": "failed" if state != "COMPLETED" else "unknown"}
        receipt = read_json(receipt_path)
        verify_receipt(receipt, read_json(directory / "package.json"))
        code = receipt["exit_code"]
        expected_exit = code if code >= 0 else 128 - code
        if receipt["job_id"] != job_id or receipt["native_id"] != native_id or exit_code != f"{expected_exit}:0":
            return snapshot
        if state != "COMPLETED" and receipt["status"] == "succeeded":
            return snapshot
        return {**snapshot, "state": receipt["status"], "receipt": receipt}
