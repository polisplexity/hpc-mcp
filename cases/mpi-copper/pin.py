"""Pin a local Open MPI rank to its assigned physical core and exec LAMMPS."""

import os
import sys


def main():
    cpus = [int(value) for value in sys.argv[1].split(",")]
    rank = int(os.environ["OMPI_COMM_WORLD_LOCAL_RANK"])
    cpu = cpus[rank]
    os.sched_setaffinity(0, {cpu})
    if os.sched_getaffinity(0) != {cpu}:
        raise RuntimeError("LAMMPS rank did not bind to its assigned CPU")
    print(f"POLIS_RANK {rank}", flush=True)
    program = "/usr/bin/lmp"
    os.execv(program, [program, *sys.argv[2:]])


if __name__ == "__main__":
    main()
