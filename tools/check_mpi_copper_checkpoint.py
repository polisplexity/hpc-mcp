"""Verify a LAMMPS checkpoint handoff through two distinct HPC MCP jobs."""

import asyncio
from datetime import date
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from hpc_mcp.slurm import SlurmProfile, observed
from hpc_mcp.worker import JOB_VERSION, MAX_FILE_BYTES, digest
from tools.check_mpi_copper import CASE, POTENTIAL, TOLERANCES, submit_receipt, verified_bytes
from tools.check_portable_job import check, schema, write_manifest
from tools.check_slurm_job import call, connect


RANKS = 2
CELLS = 8
ATOMS = 4 * CELLS**3
STEPS = 140
SPLIT = 70
STRIDE = 10
CHECKPOINT = "copper.restart"
THERMO = "copper-result.json"
RESOURCES = {"cpus": RANKS, "memory_mib": 512, "wall_time_seconds": 30}


def arguments(steps, *mode):
    return [str(RANKS), str(CELLS), str(steps), str(STRIDE), *mode]


def stage(directory):
    files = [(CASE / name) for name in ("run.py", "pin.py", "in.copper", "in.checkpoint", "in.resume")]
    files.append(POTENTIAL)
    for source in files:
        shutil.copyfile(source, directory / source.name)
    return {source.name: digest((directory / source.name).read_bytes()) for source in files}


def manifest(directory, name, argv, hashes, input_names, outputs):
    write_manifest(directory, name, {
        "version": JOB_VERSION, "runtime": "python3", "entrypoint": "run.py",
        "argv": argv, "inputs": [{"path": path, "sha256": hashes[path]} for path in input_names],
        "outputs": list(outputs), "resources": RESOURCES,
    })


def native_reference(directory):
    check(len(os.sched_getaffinity(0)) == RANKS, "Select two CPUs for the checkpoint comparison")
    subprocess.run([sys.executable, "-I", "-B", "run.py", *arguments(STEPS)],
                   cwd=directory, check=True, timeout=30, stdout=sys.stderr)
    return json.loads((directory / THERMO).read_bytes())


async def execute(session, name, result_schema, expected_artifacts, prepared=None):
    if prepared is None:
        prepared = await call(session, "hpc_prepare", {"manifest": name, "profile": "slurm"})
    result, _ = await submit_receipt(session, name, RANKS, prepared, result_schema)
    receipt = result["receipt"]
    artifacts = {item["path"]: item for item in receipt["artifacts"]}
    check(set(artifacts) == set(expected_artifacts) and not receipt["unavailable_outputs"],
          "Slurm did not return all declared outputs")
    verified = {path: verified_bytes(item) for path, item in artifacts.items()}
    thermo = json.loads(verified[THERMO])
    check(thermo["ranks"] == thermo["pinned_cpus"] == RANKS and thermo["atoms"] == ATOMS,
          "The run used a different rank configuration or atom count")
    print(f"{name}: Slurm job {receipt['native_id']} completed", file=sys.stderr)
    summary = {
        "request_id": receipt["job_id"], "native_job_id": receipt["native_id"],
        "native_state": result["native_state"], "native_exit_code": result["native_exit_code"],
        "manifest_sha256": receipt["manifest_sha256"], "resources": receipt["resources"],
        "started_at": receipt["started_at"], "finished_at": receipt["finished_at"],
        "artifacts": {path: {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
                      for path, item in artifacts.items()},
        "simulation": thermo,
    }
    return summary, verified.get(CHECKPOINT)


async def reject_modified_checkpoint(session, name, directory, checkpoint, profile):
    request = uuid4()
    job_name = f"polishpc-{request.hex}"
    path = directory / CHECKPOINT
    changed = bytes([checkpoint[0] ^ 1]) + checkpoint[1:]
    path.write_bytes(changed)
    errors = {}
    try:
        tools = (
            ("hpc_prepare", {"manifest": name, "profile": "slurm"}),
            ("hpc_slurm_submit", {"manifest": name, "request_id": str(request)}),
        )
        for tool, args in tools:
            result = await session.call_tool(tool, args)
            error = "\n".join(item.text for item in result.content if item.type == "text")
            check(result.isError and f"Input hash mismatch: {CHECKPOINT}" in error,
                  f"{tool} did not reject the changed checkpoint")
            errors[tool] = error
    finally:
        path.write_bytes(checkpoint)
    check(not (profile.location / str(request) / "intent.json").exists(),
          "The rejected request created a submission intent")
    queued = observed(["squeue", "--noheader", f"--name={job_name}", "--format=%i"])
    accounted = observed(["sacct", "--noheader", "--parsable2", "--allocations", f"--name={job_name}",
                          f"--starttime={date.today().isoformat()}", "--format=JobIDRaw"])
    check(queued == accounted == [], "The rejected request appeared in Slurm")
    return {"request_id": str(request), "altered_sha256": digest(changed), "tool_errors": errors,
            "submission_intent_created": False, "squeue_rows": queued, "sacct_rows": accounted}


def compare_samples(reference, actual):
    differences = dict.fromkeys(TOLERANCES, 0.0)
    for expected, observed_row in zip(reference, actual, strict=True):
        check(expected["step"] == observed_row["step"], "Sampled timesteps differ")
        for field, tolerance in TOLERANCES.items():
            gap = abs(expected[field] - observed_row[field])
            check(0 <= gap <= tolerance, f"Thermodynamic mismatch for {field} at step {expected['step']}")
            differences[field] = max(differences[field], gap)
    return differences


async def compare(directory, profile):
    hashes = stage(directory)
    native = native_reference(directory)
    common = ("run.py", "pin.py", POTENTIAL.name)
    manifest(directory, "continuous.json", arguments(STEPS), hashes, (*common, "in.copper"), (THERMO,))
    manifest(directory, "save.json", arguments(SPLIT, "save"), hashes,
             (*common, "in.copper", "in.checkpoint"), (THERMO, CHECKPOINT))
    result_schema = schema("result")
    async with connect(directory) as session:
        environment = await call(session, "hpc_slurm_preflight")
        check(environment["partition_visible"], "The Slurm pilot partition is unavailable")
        full, _ = await execute(session, "continuous.json", result_schema, (THERMO,))
        save, checkpoint = await execute(session, "save.json", result_schema, (THERMO, CHECKPOINT))
        check(0 < len(checkpoint) <= MAX_FILE_BYTES, "The checkpoint exceeds the portable worker limit")
        hashes[CHECKPOINT] = save["artifacts"][CHECKPOINT]["sha256"]
        (directory / CHECKPOINT).write_bytes(checkpoint)
        manifest(directory, "resume.json", arguments(STEPS - SPLIT, "resume", str(SPLIT)),
                 hashes, (*common, "in.resume", CHECKPOINT), (THERMO,))
        accepted = await call(session, "hpc_prepare", {"manifest": "resume.json", "profile": "slurm"})
        rejected = await reject_modified_checkpoint(session, "resume.json", directory, checkpoint, profile)
        resume, _ = await execute(session, "resume.json", result_schema, (THERMO,), prepared=accepted)

    jobs = (full, save, resume)
    check(len({job["native_job_id"] for job in jobs}) == len(jobs), "Slurm reused a job ID")
    full_rows = full["simulation"]["thermo"]
    save_rows, resume_rows = (item["simulation"]["thermo"] for item in (save, resume))
    check(save_rows[-1]["step"] == resume_rows[0]["step"] == SPLIT, "Checkpoint boundary shifted")
    check(native["atoms"] == ATOMS and native["lammps_version"] == full["simulation"]["lammps_version"],
          "Direct reference used different atoms or engine")
    return {
        "case": "checkpoint and restart of periodic fcc copper",
        "workload": {"cells_per_side": CELLS, "atoms": ATOMS, "ranks": RANKS,
                     "steps": STEPS, "checkpoint_step": SPLIT, "sample_every": STRIDE},
        "slurm_version": environment["version"],
        "mpi_version": subprocess.check_output(["mpirun", "--version"], text=True).splitlines()[0],
        "input_sha256": hashes,
        "checkpoint": {**save["artifacts"][CHECKPOINT], "step": SPLIT,
                       "worker_limit_bytes": MAX_FILE_BYTES, "resume_input_sha256": hashes[CHECKPOINT]},
        "native_reference": native, "continuous": full, "save": save, "resume": resume,
        "modified_checkpoint": rejected,
        "validation": {
            "absolute_tolerances": TOLERANCES,
            "continuous_vs_native": compare_samples(native["thermo"], full_rows),
            "save_vs_continuous": compare_samples([row for row in full_rows if row["step"] <= SPLIT], save_rows),
            "resume_vs_continuous": compare_samples([row for row in full_rows if row["step"] >= SPLIT], resume_rows),
            "restart_boundary": compare_samples([save_rows[-1]], [resume_rows[0]]),
        },
    }


def main():
    profile = SlurmProfile.configured()
    with TemporaryDirectory(prefix="copper-checkpoint-", dir=profile.location) as directory:
        report = asyncio.run(compare(Path(directory), profile))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
