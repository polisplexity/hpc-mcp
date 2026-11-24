"""Launch the staged heat fixture on the CPU mask assigned to this job."""

import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter


def main():
    ranks, rows, cols, steps = map(int, sys.argv[1:])
    cpus = sorted(os.sched_getaffinity(0))
    if ranks not in (1, 2, 4) or ranks != len(cpus):
        raise ValueError("MPI rank count must match the worker's allocated CPUs")

    binary = Path("heat").resolve()
    binary.chmod(0o700)
    command = [
        "/usr/bin/mpirun", "--host", f"localhost:{ranks}", "--bind-to", "none",
        "--mca", "pml", "ob1", "--mca", "btl", "self,tcp", "--mca", "btl_tcp_if_include", "lo",
        "-n", str(ranks), str(binary), *map(str, (rows, cols, steps, *cpus)),
    ]
    start = perf_counter()
    run = subprocess.run(
        command, stdout=subprocess.PIPE, check=True, timeout=25,
        env={**os.environ, "PATH": "/usr/bin:/bin", "TMPDIR": str(Path.cwd())},
    )
    report = json.loads(run.stdout)
    report["launcher_seconds"] = perf_counter() - start
    Path("heat-result.json").write_bytes((json.dumps(report, sort_keys=True) + "\n").encode())


if __name__ == "__main__":
    main()
