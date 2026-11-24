"""Launch the MCP server alongside a read-only observer for its MPI cancellation test."""

import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import UUID

from hpc_mcp.client import JOB_ROOT
from hpc_mcp.slurm import SlurmProfile, observed
from hpc_mcp.worker import JOB_VERSION, digest
from tools.check_mpi_copper import CASE, POTENTIAL


MANIFEST = "mpi-copper-cancel.json"
RANKS = 2
RESOURCES = {"cpus": RANKS, "memory_mib": 512, "wall_time_seconds": 30}


def stage(directory):
    paths = [CASE / name for name in ("run.py", "pin.py", "in.copper")] + [POTENTIAL]
    inputs = []
    for source in paths:
        shutil.copyfile(source, directory / source.name)
        inputs.append({"path": source.name, "sha256": digest(source.read_bytes())})
    manifest = {
        "version": JOB_VERSION, "runtime": "python3", "entrypoint": "run.py",
        "argv": ["2", "32", "500", "50"], "inputs": inputs, "outputs": ["copper-result.json"],
        "resources": RESOURCES,
    }
    (directory / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def processes():
    running = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            stat = (entry / "stat").read_text()
            _, rest = stat.split("(", 1)
            command, fields = rest.rsplit(")", 1)
            fields = fields.split()
        except (OSError, ValueError):
            continue
        if command in {"lmp", "mpirun", "prterun", "prted"} and fields[0] not in {"Z", "X"}:
            running[int(entry.name)] = {"process": command, "start_ticks": int(fields[19])}
    return running


def queue(job_name):
    return observed(["squeue", "--noheader", f"--user={os.getuid()}", f"--name={job_name}", "--format=%i|%T"])


def snapshot(request_id, manifest, before):
    job_name = f"polishpc-{request_id.hex}"
    accounting = observed([
        "sacct", "--noheader", "--parsable2", "--allocations", f"--user={os.getuid()}", f"--name={job_name}",
        f"--starttime={(date.today() - timedelta(days=1)).isoformat()}",
        "--format=JobIDRaw,State%40,AllocCPUS,ExitCode",
    ])
    profile = SlurmProfile.configured()
    job_directory = profile.location / str(request_id)
    return {
        "request_id": str(request_id), "manifest": manifest, "running": before,
        "final_queue": queue(job_name), "accounting": accounting, "remaining_processes": processes(),
        "cancel_acknowledged": (job_directory / "cancel-ack.json").is_file(),
        "worker_receipt_written": (job_directory / "receipt.json").is_file(),
    }


def emit(record):
    print(f"CANCEL_AUDIT {json.dumps(record, sort_keys=True)}", file=sys.stderr, flush=True)


def audit(directory, request_id, manifest):
    job_name = f"polishpc-{request_id.hex}"
    before = None
    next_accounting = 0.0
    env = {**os.environ, JOB_ROOT: str(directory)}
    with subprocess.Popen([sys.executable, "-m", "hpc_mcp.server"], env=env) as server:
        while server.poll() is None:
            live = processes()
            if before is None and sum(item["process"] == "lmp" for item in live.values()) == RANKS:
                rows = queue(job_name)
                if rows and len(rows) == 1 and rows[0][1] == "RUNNING":
                    before = {"queue": rows[0], "processes": live}
            if before and not live and monotonic() >= next_accounting:
                record = snapshot(request_id, manifest, before)
                rows = record["accounting"]
                if rows and len(rows) == 1 and rows[0][1].split()[0] == "CANCELLED" and record["final_queue"] == []:
                    emit(record)
                    return server.wait()
                next_accounting = monotonic() + 1
            sleep(0.1)
    emit(snapshot(request_id, manifest, before))
    return server.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id", type=UUID)
    args = parser.parse_args()
    profile = SlurmProfile.configured()
    with TemporaryDirectory(prefix="mpi-cancel-", dir=profile.location) as workspace:
        directory = Path(workspace)
        manifest = stage(directory)
        return audit(directory, args.request_id, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
