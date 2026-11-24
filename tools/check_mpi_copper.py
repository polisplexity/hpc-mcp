"""Run the fixed LAMMPS copper simulation through the HPC MCP Slurm profile."""

import argparse
import asyncio
import base64
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from hpc_mcp.slurm import SlurmProfile, observed
from hpc_mcp.worker import JOB_VERSION, digest
from tools.check_mpi_stencil import RANKS, summarize, topology
from tools.check_portable_job import check, schema, write_manifest
from tools.check_slurm_job import call, connect, terminal


CASE = Path(__file__).resolve().parents[1] / "cases" / "mpi-copper"
POTENTIAL = Path("/usr/share/lammps/potentials/Cu_u3.eam")
WORKLOAD = (32, 140, 20)
ORDERS = (RANKS, (2, 4, 1), (4, 1, 2))
MAX_ENERGY_DEVIATION = 2e-3
TOLERANCES = {
    "temperature_k": 2e-3, "potential_ev_per_atom": 1e-6,
    "total_ev_per_atom": 1e-6, "pressure_bar": 0.02,
}


def stage(directory, workload):
    paths = [CASE / name for name in ("run.py", "in.copper", "pin.py")] + [POTENTIAL]
    inputs = []
    for source in paths:
        shutil.copyfile(source, directory / source.name)
        inputs.append({"path": source.name, "sha256": digest(source.read_bytes())})
    for ranks in RANKS:
        write_manifest(directory, f"ranks-{ranks}.json", {
            "version": JOB_VERSION, "runtime": "python3", "entrypoint": "run.py",
            "argv": list(map(str, (ranks, *workload))), "inputs": inputs,
            "outputs": ["copper-result.json"],
            "resources": {"cpus": ranks, "memory_mib": 512, "wall_time_seconds": 30},
        })
    return {item["path"]: item["sha256"] for item in inputs}


async def submit_receipt(session, manifest, ranks, prepared, result_schema):
    request_id = str(uuid4())
    started = perf_counter()
    submitted = await call(session, "hpc_slurm_submit", {
        "manifest": manifest, "request_id": request_id,
    })
    check(submitted["state"] == "submitted", "Slurm did not acknowledge the copper simulation")
    result = await terminal(session, request_id)
    receipt_seconds = perf_counter() - started
    receipt = result.get("receipt") or {}
    if result["state"] != "succeeded":
        stderr = (receipt.get("logs") or {}).get("stderr") or {}
        failure = base64.b64decode(stderr.get("base64", "")).decode(errors="replace")
        raise RuntimeError(f"Slurm job {submitted['native_id']} returned {result['state']}\n{failure}")
    result_schema.validate(receipt)
    native_id = submitted["native_id"]
    check(result["job_id"] == receipt["job_id"] == request_id
          and result["native_id"] == receipt["native_id"] == native_id, "Slurm job identity changed")
    check(receipt["manifest_sha256"] == prepared["manifest_sha256"], "Prepared manifest changed")
    check(result["native_state"] == "COMPLETED" and result["native_exit_code"] == "0:0"
          and receipt["exit_code"] == 0, "Slurm and the worker report different outcomes")
    accounting = observed([
        "sacct", "--noheader", "--parsable2", "--allocations", f"--jobs={native_id}",
        "--format=JobIDRaw,AllocCPUS,State,ExitCode",
    ])
    check(accounting == [[native_id, str(ranks), "COMPLETED", "0:0"]], "Slurm CPU count differs")
    return result, receipt_seconds


def verified_bytes(artifact):
    data = base64.b64decode(artifact["base64"], validate=True)
    check(len(data) == artifact["size_bytes"] and digest(data) == artifact["sha256"],
          "Copper artifact failed size or digest verification")
    return data


async def measure(session, ranks, prepared, result_schema):
    result, receipt_seconds = await submit_receipt(session, f"ranks-{ranks}.json", ranks, prepared, result_schema)
    receipt = result["receipt"]
    artifact, = receipt["artifacts"]
    check(artifact["path"] == "copper-result.json", "Unexpected thermodynamics artifact")
    sample = json.loads(verified_bytes(artifact))
    check(sample["ranks"] == sample["pinned_cpus"] == ranks, "MPI rank affinity differs")
    check(all(math.isfinite(sample[key]) for key in ("launcher_seconds", "kernel_seconds"))
          and 0 < sample["kernel_seconds"] <= sample["launcher_seconds"] <= receipt_seconds,
          "Invalid timing evidence")
    print(f"Slurm job {receipt['native_id']}: {ranks} ranks, LAMMPS loop {sample['kernel_seconds']:.3f}s",
          file=sys.stderr)
    return {
        **sample, "request_id": receipt["job_id"], "native_job_id": receipt["native_id"],
        "allocated_cpus": ranks, "native_state": result["native_state"],
        "native_exit_code": result["native_exit_code"], "artifact_sha256": artifact["sha256"],
        "manifest_sha256": receipt["manifest_sha256"], "started_at": receipt["started_at"],
        "finished_at": receipt["finished_at"], "submit_to_receipt_seconds": receipt_seconds,
    }


def compare_thermo(samples):
    reference = next(sample for sample in samples if sample["ranks"] == 1)["thermo"]
    maxima = dict.fromkeys(TOLERANCES, 0.0)
    energy_deviation = 0.0
    for sample in samples:
        rows = sample["thermo"]
        initial_energy = rows[0]["total_ev_per_atom"]
        check(abs(rows[0]["temperature_k"] - 900) <= TOLERANCES["temperature_k"],
              "Unexpected initial temperature")
        for observed_row, reference_row in zip(rows, reference, strict=True):
            check(observed_row["step"] == reference_row["step"], "Thermodynamic steps differ")
            energy_deviation = max(energy_deviation, abs(observed_row["total_ev_per_atom"] - initial_energy))
            for field in TOLERANCES:
                maxima[field] = max(maxima[field], abs(observed_row[field] - reference_row[field]))
    for field, limit in TOLERANCES.items():
        check(maxima[field] <= limit, f"Thermodynamic mismatch across MPI runs for {field}")
    check(energy_deviation <= MAX_ENERGY_DEVIATION, "Energy deviation exceeds the NVE tolerance")
    return {"max_difference_vs_one_rank": maxima, "absolute_tolerances": TOLERANCES,
            "max_energy_deviation_ev_per_atom": energy_deviation,
            "energy_deviation_limit_ev_per_atom": MAX_ENERGY_DEVIATION}


async def compare(directory, smoke):
    workload = (12, 12, 3) if smoke else WORKLOAD
    inputs = stage(directory, workload)
    layout = topology()
    result_schema = schema("result")
    orders = (RANKS,) if smoke else ORDERS
    async with connect(directory) as session:
        profile = await call(session, "hpc_slurm_preflight")
        check(profile["partition_visible"], "The Slurm pilot partition is unavailable")
        prepared = {}
        for ranks in RANKS:
            prepared[ranks] = await call(session, "hpc_prepare", {
                "manifest": f"ranks-{ranks}.json", "profile": "slurm",
            })
        samples = [
            await measure(session, ranks, prepared[ranks], result_schema) for order in orders for ranks in order
        ]
    cells, steps, stride = workload
    check({(sample["atoms"], sample["steps"]) for sample in samples} == {(4 * cells**3, steps)},
          "Workload dimensions changed")
    packages = subprocess.check_output(["dpkg-query", "-W", "lammps", "lammps-data"], text=True)
    return {
        "case": "microcanonical thermal relaxation of periodic fcc copper",
        "workload": {"cells_per_side": cells, "atoms": 4 * cells**3, "steps": steps,
                     "sample_every": stride, "timestep_ps": 0.002, "initial_temperature_k": 900.0},
        "packages": dict(line.split() for line in packages.splitlines()),
        "mpi_version": subprocess.check_output(["mpirun", "--version"], text=True).splitlines()[0],
        "slurm_version": profile["version"], "topology": layout, "input_sha256": inputs,
        "validation": compare_thermo(samples), "samples": samples, "summary": summarize(samples),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Run twelve steps per rank count")
    args = parser.parse_args()
    profile = SlurmProfile.configured()
    with TemporaryDirectory(prefix="mpi-copper-", dir=profile.location) as workspace:
        report = asyncio.run(compare(Path(workspace), args.smoke))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
