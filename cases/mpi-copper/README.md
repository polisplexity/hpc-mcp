# MPI molecular dynamics of crystalline copper

The [agent temperature sweep](TEMPERATURE_SWEEP.md) exercises recipe
discovery, parameterized preparation and retry through HPC MCP.

The experiment models how a periodic face-centered cubic copper crystal
redistributes energy after its initial velocities are set to 900 K. LAMMPS
integrates the motion in the microcanonical ensemble at fixed volume, with a
2 fs timestep and the Cu_u3 embedded-atom potential. The potential comes from
Debian's lammps-data package. The scientific fixture is an ideal bulk crystal
and the measured trajectory describes that model. [Foiles, Baskes and Daw, 1986](https://doi.org/10.1103/PhysRevB.33.7983)

The project's input and launcher are under the repository's [MIT license](../../LICENSE).
The Docker build obtains LAMMPS and its data from Debian. [LAMMPS license](https://docs.lammps.org/stable/Intro_opensource.html)

## Reproduce

Use the [MPI stencil build recipe](../mpi-stencil/README.md#reproduce-the-comparison)
to build the base image `polisplexity-hpc/mpi-heat:local`. From a committed
checkout of this case, build the LAMMPS overlay. The package comes from the
same signed Debian snapshot as Open MPI.

```sh
revision=$(git rev-parse HEAD)
image=polisplexity-hpc/mpi-copper:local
git archive "$revision" cases/mpi-copper/in.copper \
  cases/mpi-copper/run.py cases/mpi-copper/pin.py \
  cases/mpi-copper/docker/Dockerfile cases/mpi-stencil/docker/install.sh \
  tools/check_mpi_copper.py |
  docker build --file cases/mpi-copper/docker/Dockerfile \
    --label "org.opencontainers.image.revision=$revision" --tag "$image" -

# Set CPU IDs for four distinct physical cores on one NUMA node.
cpu_ids=0,1,2,3
POLISPLEXITY_SLURM_TEST_CPUS=4 POLISPLEXITY_SLURM_TEST_CPUSET="$cpu_ids" \
  bash cases/portable-python/docker/check.sh "$image" > copper-report.json
```

The runner reuses the isolated one-node Docker Slurm pilot. Each job asks for
one Slurm task, 512 MiB and a CPU per MPI rank, with a 30-second worker wall
limit. Open MPI launches the ranks over loopback TCP and the wrapper binds
each to a separate physical core. The launcher selects an in-memory PMIx
datastore and uses one OpenMP and BLAS thread per rank. Each of the three
rounds changes the rank order, with each configuration occupying each position
once.

HPC MCP prepares the file hashes, submits the job to Slurm and recovers the
thermodynamic trajectory as a JSON artifact. The verifier checks the job
identity and exit code, Slurm accounting for allocated CPUs, rank affinity,
artifact hashes and thermodynamic agreement at every recorded step. LAMMPS
reports temperature in kelvin and pressure in bar. The artifact reports
energies in eV per atom. Tests include atom conservation and maximum
total-energy deviation from the initial state.

The loop time is the LAMMPS integration timer. Launcher time also includes
MPI setup, initialization and shutdown. Submit-to-receipt time includes
scheduling and the MCP status polling interval. Performance applies to one
node with this transport and package build.

The one-rank calibration used 131,072 atoms and 100 steps. It took 14.10 s
through the launcher. The comparison holds the grid fixed at 32 × 32 × 32
conventional fcc cells and uses 140 steps, or 0.28 ps, with a thermodynamic
sample every 20 steps.

## CIMAT results

Nine measured jobs ran on November 24, 2026, with LAMMPS 4 Jul 2026,
Open MPI 6.0.0rc2 and Slurm 26.05.5. Each row is the median of three jobs.
Times are in seconds. [Raw runs and provenance](evidence/cimat-lammps-20261124.json)

| MPI ranks | Integration | Integration range | Speedup | Parallel efficiency | Launcher | Submit to receipt |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 18.33 | 18.32–18.35 | 1.00× | 100% | 19.34 | 20.33 |
| 2 | 9.37 | 9.34–9.40 | 1.96× | 98% | 10.28 | 11.19 |
| 4 | 5.03 | 5.02–5.04 | 3.65× | 91% | 5.88 | 7.39 |

All runs retained 131,072 atoms and matched the one-rank thermodynamic
trajectory within tolerance. The maximum temperature difference across runs
was 1.51 × 10⁻¹¹ K. The largest sampled total-energy deviation from the
initial value was 1.13 × 10⁻⁴ eV per atom. A direct one-rank run in the
same image reproduced the thermodynamic samples.

## Capacity follow-up

This exploratory benchmark fits the Docker profile's four-core and 30-second
worker limits. A future capacity review can use these measurements when an
applied workload specifies its trajectory length and turnaround target.

At four ranks, a median of 94.29% of integration time went to the force
calculation and 3.60% to MPI communication. A 10 ps trajectory would need
5,000 steps, about three minutes of integration if the measured four-rank
rate holds. Eight physical cores on one node and five minutes per job are
a candidate configuration for a future trial. The time estimate is an
extrapolation from the 140-step segment. The benchmark measures up to
four cores.

## Checkpoint and restart

The CIMAT pilot compared 140 continuous steps with two separate 70-step jobs
using the same model, engine and two MPI ranks on one node. The smaller
crystal had 2,048 atoms. LAMMPS wrote a 181,128-byte binary checkpoint at
step 70. The client recovered those bytes from the first HPC MCP receipt and
used the verified SHA-256 as an input to the second job. The resumed input
reapplies the EAM potential and the NVE integrator. [LAMMPS restart format](https://docs.lammps.org/read_restart.html) · [EAM restart behavior](https://docs.lammps.org/stable/pair_eam.html)

All three Slurm jobs completed and retained 2,048 atoms. The continuous
Slurm run reproduced the direct reference. Across resumed samples, the
maximum differences from the continuous run were 9.66 × 10⁻¹³ K in
temperature, 2.44 × 10⁻¹⁴ eV per atom in total energy, and 1.02 × 10⁻¹⁰
bar in pressure. Both preparation and submission rejected a one-byte change
to the checkpoint. The rejected request created zero Slurm queue or
accounting records. [Recorded checkpoint evidence](evidence/cimat-lammps-checkpoint-20261124.json)

The test covers a scheduled handoff between jobs on the same LAMMPS build
and platform. Its checkpoint fits the portable contract's 256 KiB limit
for each input and output file.

### Reproduce the checkpoint test

First build the LAMMPS image using the [copper recipe](#reproduce). Then add
the checkpoint fixture and verifier from a committed checkout.

```sh
revision=$(git rev-parse HEAD)
image=polisplexity-hpc/mpi-copper-checkpoint:local
git archive "$revision" cases/mpi-copper/run.py cases/mpi-copper/in.checkpoint \
  cases/mpi-copper/in.resume cases/mpi-copper/docker/Dockerfile.checkpoint \
  tools/check_mpi_copper.py tools/check_mpi_copper_checkpoint.py |
  docker build --file cases/mpi-copper/docker/Dockerfile.checkpoint \
    --label "org.opencontainers.image.revision=$revision" --tag "$image" -

# Set CPU IDs for two distinct physical cores on one NUMA node.
cpu_ids=0,1
POLISPLEXITY_SLURM_TEST_CPUS=2 POLISPLEXITY_SLURM_TEST_CPUSET="$cpu_ids" \
  bash cases/portable-python/docker/check.sh "$image" > checkpoint-report.json
```
