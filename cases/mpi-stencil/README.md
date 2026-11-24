# MPI heat diffusion on the Slurm Docker pilot

This case runs a two-dimensional, periodic heat stencil in a fixed grid of
1,536 × 2,048 cells for 128 sweeps. The same C program uses 1, 2 or 4 Open MPI
processes. Each process owns contiguous rows and exchanges its two boundary
rows with its neighbors through `MPI_Sendrecv`. The fixture is synthetic and
available under the repository's [MIT license](../../LICENSE).

HPC MCP uses the existing Slurm job contract to prepare and submit a Python
launcher, then retrieves its receipt and result artifact over MCP stdio.
Slurm grants one task with one, two or four CPUs on a single node. Open MPI
starts the corresponding number of local ranks. Each rank pins itself to a
separate physical core. The comparison uses the TCP loopback transport inside
one container. Shared-memory MPI transport and multi-node scaling are outside
the measured scope. [Open MPI TCP transport](https://docs.open-mpi.org/en/main/tuning-apps/networking/tcp.html)

## Reproduce the comparison

Run on an authorized Linux x86-64 Docker host, from a committed checkout that
includes this case. Select four distinct physical cores on the same NUMA node
that Docker is allowed to use. Inspect the host topology with
`lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE` and set `cpu_ids` to their comma-separated
logical CPU IDs. The base build uses the
[public Slurm Docker recipe](../portable-python/SLURM.md#reproduce-from-a-clean-checkout).

```sh
bash cases/portable-python/docker/build.sh

revision=$(git rev-parse HEAD)
image=polisplexity-hpc/mpi-heat:local
git archive "$revision" cases/mpi-stencil/heat.c cases/mpi-stencil/run.py \
  cases/mpi-stencil/docker/Dockerfile cases/mpi-stencil/docker/install.sh \
  cases/portable-python/docker/start.sh tools/check_mpi_stencil.py |
  docker build --file cases/mpi-stencil/docker/Dockerfile \
    --label "org.opencontainers.image.revision=$revision" --tag "$image" -

# Replace the example with your four selected logical CPU IDs.
cpu_ids=0,1,2,3
POLISPLEXITY_SLURM_TEST_CPUS=4 POLISPLEXITY_SLURM_TEST_CPUSET="$cpu_ids" \
  bash cases/portable-python/docker/check.sh "$image" > mpi-report.json
```

The container runs on an isolated Docker network with one GiB of RAM. Each
Slurm job requests 512 MiB and the worker applies a 30-second wall limit.
The launcher supplies a job-local home and temporary directory because the
worker starts with a minimal environment. It selects the PMIx hash datastore
to stay within the worker's 256 KiB file-size limit.
The verifier warms up each rank count once, then interleaves five timed runs
per rank count. It checks each allocation with `sacct`, validates the receipt
and result artifact hash, and compares the final field between all runs.
The field digest is the SHA-256 of the ordered row digests over the final
double-precision values. The analytic check uses the exact discrete decay of
the initialized Fourier modes.

The kernel time covers the stencil and boundary exchanges and reports the
slowest rank. Launcher time also includes MPI startup and shutdown, field
initialization, and the correctness checks. Scheduler queue time is outside
both measurements.

## CIMAT results

The Docker pilot ran the comparison on November 23, 2026, with Slurm 26.05.5
and Open MPI 6.0.0rc2. Times are in seconds. [Recorded evidence](evidence/cimat-mpi-20261123.json)

| MPI ranks | Kernel median | Kernel range | Kernel speedup | Parallel efficiency | Launcher median | Launcher speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.542 | 0.511–0.552 | 1.00× | 100% | 1.258 | 1.00× |
| 2 | 0.286 | 0.272–0.288 | 1.90× | 95% | 0.995 | 1.26× |
| 4 | 0.209 | 0.207–0.221 | 2.59× | 65% | 0.919 | 1.37× |

The 18 benchmark jobs, including warm-ups, returned the same final-field
digest and agreed with the analytic solution to a maximum absolute error of
4.72 × 10⁻¹⁵. The one-rank reference executed directly in the same image
returned the same field digest.

The current allocation is sufficient for this case. Moving from two to four
cores saved 76 ms of median launcher time, about 8%. A resource request would
need a concrete workload whose size or deadline exceeds the current
allocation. The measured efficiency describes this grid, runtime and
transport on one node.
