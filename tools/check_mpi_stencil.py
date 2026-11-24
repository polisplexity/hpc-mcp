"""Measure a fixed MPI heat stencil through actual HPC MCP Slurm calls."""

import argparse
import asyncio
import base64
import json
import math
import os
from pathlib import Path
import re
import shutil
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from hpc_mcp.slurm import SlurmProfile, observed
from hpc_mcp.worker import JOB_VERSION, digest
from tools.check_portable_job import check, schema, write_manifest
from tools.check_slurm_job import call, connect, terminal


CASE = Path(__file__).resolve().parents[1] / "cases" / "mpi-stencil"
RANKS = (1, 2, 4)
WORKLOAD = (1536, 2048, 128)
SAMPLE_ORDERS = ((1, 2, 4), (4, 1, 2), (2, 4, 1), (4, 2, 1), (1, 4, 2))
MAX_ERROR = 2e-12


def topology():
    cores, domains = set(), set()
    for cpu in os.sched_getaffinity(0):
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}")
        package = (root / "topology/physical_package_id").read_text().strip()
        core = (root / "topology/core_id").read_text().strip()
        nodes = sorted(path.name for path in root.glob("node[0-9]*"))
        cores.add((package, core))
        domains.update(nodes or ["socket:" + package])
    check(len(os.sched_getaffinity(0)) == len(cores) == 4 and len(domains) == 1,
          "Select four distinct physical cores on one NUMA node for the MPI test")
    return {"physical_cores": len(cores), "affinity_cpus": 4, "numa_domains": len(domains)}


def stage(directory, workload):
    inputs = []
    for name in ("run.py", "heat"):
        shutil.copyfile(CASE / name, directory / name)
        inputs.append({"path": name, "sha256": digest((directory / name).read_bytes())})
    for ranks in RANKS:
        write_manifest(directory, f"ranks-{ranks}.json", {
            "version": JOB_VERSION, "runtime": "python3", "entrypoint": "run.py",
            "argv": [str(rank_arg) for rank_arg in (ranks, *workload)],
            "inputs": inputs, "outputs": ["heat-result.json"],
            "resources": {"cpus": ranks, "memory_mib": 512, "wall_time_seconds": 30},
        })
    return {item["path"]: item["sha256"] for item in inputs}


async def measure(session, ranks, prepared, result_schema):
    request_id = str(uuid4())
    submitted = await call(session, "hpc_slurm_submit", {
        "manifest": f"ranks-{ranks}.json", "request_id": request_id,
    })
    check(submitted["state"] == "submitted", "The scheduler did not acknowledge the MPI job")
    status = await terminal(session, request_id)
    receipt = status.get("receipt", {})
    if status["state"] != "succeeded":
        logs = receipt.get("logs") or {}
        error_log = logs.get("stderr") or {}
        diagnostic = base64.b64decode(error_log.get("base64", "")).decode(errors="replace")
        raise RuntimeError(f"MPI job {submitted['native_id']} finished as {status['state']}\n{diagnostic}")
    result_schema.validate(receipt)
    native_id = submitted["native_id"]
    check(status["job_id"] == receipt["job_id"] == request_id
          and status["native_id"] == receipt["native_id"] == native_id, "MPI job identity changed")
    check(receipt["manifest_sha256"] == prepared["manifest_sha256"], "The prepared MPI manifest changed")
    check(status["native_state"] == "COMPLETED" and status["native_exit_code"] == "0:0"
          and receipt["exit_code"] == 0, "The MPI job exit evidence disagrees")
    accounting = observed([
        "sacct", "--noheader", "--parsable2", "--allocations", f"--jobs={native_id}",
        "--format=JobIDRaw,AllocCPUS,State,ExitCode",
    ])
    check(accounting == [[native_id, str(ranks), "COMPLETED", "0:0"]], "The allocation CPU count differs")

    artifact, = receipt["artifacts"]
    data = base64.b64decode(artifact["base64"], validate=True)
    check(artifact["path"] == "heat-result.json" and digest(data) == artifact["sha256"],
          "The MPI artifact failed digest verification")
    sample = json.loads(data)
    check(sample["ranks"] == sample["pinned_cpus"] == ranks, "MPI ranks did not use separate CPUs")
    check(math.isfinite(sample["max_abs_error"]) and 0 <= sample["max_abs_error"] <= MAX_ERROR,
          "The final field disagrees with the analytic solution")
    check(math.isfinite(sample["kernel_seconds"]) and math.isfinite(sample["launcher_seconds"])
          and 0 < sample["kernel_seconds"] <= sample["launcher_seconds"], "Invalid timing evidence")
    check(bool(re.fullmatch("[a-f0-9]{64}", sample["field_digest"])), "Invalid field digest")
    print(f"MPI ranks={ranks}, Slurm job={native_id}, kernel={sample['kernel_seconds']:.3f}s", file=sys.stderr)
    return {
        **sample, "request_id": request_id, "native_job_id": native_id,
        "allocated_cpus": ranks, "native_state": status["native_state"],
        "native_exit_code": status["native_exit_code"], "artifact_sha256": artifact["sha256"],
        "manifest_sha256": receipt["manifest_sha256"],
        "started_at": receipt["started_at"], "finished_at": receipt["finished_at"],
    }


def summarize(samples):
    basetime = median(row["kernel_seconds"] for row in samples if row["ranks"] == 1)
    baseline_launch = median(row["launcher_seconds"] for row in samples if row["ranks"] == 1)
    rows = []
    for ranks in RANKS:
        subset = [row for row in samples if row["ranks"] == ranks]
        kernel = [row["kernel_seconds"] for row in subset]
        launcher = median(row["launcher_seconds"] for row in subset)
        center = median(kernel)
        rows.append({
            "ranks": ranks, "samples": len(subset), "median_kernel_seconds": center,
            "min_kernel_seconds": min(kernel), "max_kernel_seconds": max(kernel),
            "kernel_speedup": basetime / center, "kernel_parallel_efficiency": basetime / (center * ranks),
            "median_launcher_seconds": launcher, "launcher_speedup": baseline_launch / launcher,
        })
    return rows


async def compare(directory, smoke):
    workload = (128, 128, 8) if smoke else WORKLOAD
    inputs = stage(directory, workload)
    result_schema = schema("result")
    layout = topology()
    orders = (RANKS,) if smoke else SAMPLE_ORDERS
    async with connect(directory) as session:
        profile = await call(session, "hpc_slurm_preflight")
        check(profile["partition_visible"], "The MPI test partition is unavailable")
        prepared = {}
        for ranks in RANKS:
            prepared[ranks] = await call(session, "hpc_prepare", {"manifest": f"ranks-{ranks}.json", "profile": "slurm"})
        warmup = [] if smoke else [
            await measure(session, ranks, prepared[ranks], result_schema) for ranks in RANKS
        ]
        samples = [
            await measure(session, ranks, prepared[ranks], result_schema) for order in orders for ranks in order
        ]
    hashes = {item["field_digest"] for item in warmup + samples}
    check(len(hashes) == 1, "The final field changes with MPI process count")
    return {
        "case": "periodic two-dimensional heat stencil",
        "scope": "one Docker Slurm node, one MPI rank per physical core",
        "mpi_version": subprocess.check_output(["mpirun", "--version"], text=True).splitlines()[0],
        "slurm_version": profile["version"],
        "topology": layout,
        "dimensions": {"rows": workload[0], "columns": workload[1], "steps": workload[2]},
        "input_hashes": inputs,
        "source_sha256": digest((CASE / "heat.c").read_bytes()),
        "field_digest": hashes.pop(),
        "maximum_absolute_error": max(item["max_abs_error"] for item in warmup + samples),
        "warmup": warmup, "samples": samples, "summary": summarize(samples),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Exercise one small job per process count")
    args = parser.parse_args()
    profile = SlurmProfile.configured()
    with TemporaryDirectory(prefix="mpi-stencil-", dir=profile.location) as workspace:
        report = asyncio.run(compare(Path(workspace), args.smoke))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
