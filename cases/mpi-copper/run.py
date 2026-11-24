"""Launch the staged copper simulation and record LAMMPS thermodynamics."""

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter


THERMO_HEADER = "Step Atoms Temp PotEng TotEng Press".split()
THERMO_KEYS = ("temperature_k", "potential_ev_per_atom", "total_ev_per_atom", "pressure_bar")


def collect(output, ranks, cells, steps, sample_every):
    rank_lines = re.findall(r"^POLIS_RANK (\d+)$", output, re.MULTILINE)
    if sorted(map(int, rank_lines)) != list(range(ranks)):
        raise ValueError("Expected one successful affinity check from each local MPI rank")

    atoms = 4 * cells**3
    loop = re.search(r"^Loop time of (\S+) on (\d+) procs? for (\d+) steps with (\d+) atoms",
                     output, re.MULTILINE)
    if loop is None or tuple(map(int, loop.groups()[1:])) != (ranks, steps, atoms):
        raise ValueError("LAMMPS did not complete the requested simulation")
    if not re.search(r"^Dangerous builds\s*=\s*0\s*$", output, re.MULTILINE):
        raise ValueError("LAMMPS reported a potentially unsafe neighbor list")

    rows = []
    thermo = False
    for line in output[:loop.start()].splitlines():
        fields = line.split()
        if fields == THERMO_HEADER:
            thermo = True
        elif thermo and len(fields) == 6 and all(value.isdigit() for value in fields[:2]):
            step, count = map(int, fields[:2])
            temperature, potential, total, pressure = map(float, fields[2:])
            values = (temperature, potential / atoms, total / atoms, pressure)
            if count != atoms or not all(map(math.isfinite, values)):
                raise ValueError("LAMMPS lost atoms or emitted non-finite thermodynamics")
            rows.append({"step": step, **dict(zip(THERMO_KEYS, values))})
    expected = [*range(0, steps, sample_every), steps]
    if [row["step"] for row in rows] != expected:
        raise ValueError("LAMMPS did not return every requested thermodynamic sample")
    version = re.search(r"^LAMMPS \(([^)]+)\)", output, re.MULTILINE)
    grid = re.search(r"^\s*(\d+) by (\d+) by (\d+) MPI processor grid", output, re.MULTILINE)
    grid_shape = list(map(int, grid.groups())) if grid else []
    if version is None or math.prod(grid_shape) != ranks or len(grid_shape) != 3:
        raise ValueError("LAMMPS did not identify its version and MPI domain decomposition")
    breakdown = {}
    for line in output[loop.end():].splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 6 and parts[0] in ("Pair", "Neigh", "Comm"):
            breakdown[parts[0]] = float(parts[-1])
    if set(breakdown) != {"Pair", "Neigh", "Comm"} or not all(0 <= value <= 100 for value in breakdown.values()):
        raise ValueError("LAMMPS did not report valid force, neighbor and communication timings")
    return {
        "lammps_version": version[1], "ranks": ranks, "pinned_cpus": len(rank_lines),
        "processor_grid": grid_shape, "atoms": atoms, "steps": steps,
        "kernel_seconds": float(loop[1]), "timing_share_percent": breakdown, "thermo": rows,
    }


def main():
    ranks, cells, steps, sample_every = map(int, sys.argv[1:])
    cpus = sorted(os.sched_getaffinity(0))
    if ranks not in (1, 2, 4) or ranks != len(cpus):
        raise ValueError("The number of MPI ranks must match the worker CPU affinity")
    workspace = str(Path.cwd())
    command = [
        "/usr/bin/mpirun", "--host", f"localhost:{ranks}", "--bind-to", "none",
        "--mca", "pml", "ob1", "--mca", "btl", "self,tcp", "--mca", "btl_tcp_if_include", "lo",
        "-n", str(ranks), sys.executable, "-I", "-B", "pin.py", ",".join(map(str, cpus)),
        "-in", "in.copper", "-log", "none", "-nocite",
        "-var", "cells", str(cells), "-var", "steps", str(steps),
        "-var", "sample_every", str(sample_every), "-var", "potential", "Cu_u3.eam",
    ]
    started = perf_counter()
    trial = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=27, text=True,
        env={
            **os.environ, "PATH": "/usr/bin:/bin", "HOME": workspace,
            "TMPDIR": workspace, "PMIX_MCA_gds": "hash", "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        },
    )
    elapsed = perf_counter() - started
    if trial.returncode:
        sys.stderr.write(trial.stdout[-8192:])
        trial.check_returncode()
    try:
        report = collect(trial.stdout, ranks, cells, steps, sample_every)
    except ValueError:
        sys.stderr.write(trial.stdout[-8192:])
        raise
    report["launcher_seconds"] = elapsed
    Path("copper-result.json").write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
