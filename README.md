# Polisplexity HPC MCP

Open project for letting MCP-capable clients inspect compute accounts, prepare
execution environments and run versioned jobs on high-performance computing
infrastructure.

Use the [alpha installation and Hermes acceptance test](INSTALL.md) to
inspect an authorized SSH node, run R and retrieve the verified output from
a second Hermes session. The installation guide also includes the
[Slurm and Docker copper pilot](INSTALL.md#slurm-and-docker-copper-pilot).
Use the [managed SSH environment test](cases/ssh-environment/README.md) to
inspect an authorized Linux account, install a locked dependency and run and
repeat an independent batch through Hermes.
The [R over SSH case](cases/ssh-r-environment/README.md) lets Hermes discover
whether native R can run a job and reuse an approved Docker image when needed.
The [node storage case](cases/ssh-r-environment/STORAGE.md) runs that same
script against a dataset already on the SSH host and verifies the stored
result by reference.

Start with the [integration inventory](docs/INVENTORY.md), the
[CIMAT connectivity pilot](cases/cimat-guanajuato/README.md) and
[the portable Python case](cases/portable-python/README.md).
[RFC 0001](docs/rfc/0001-hpc-job-contract.md) proposes the broader interface.
[The master record](MASTER_TEST_RECORD.md) distinguishes access evidence from
MCP execution evidence.

## Reproduce the Slurm pilot

On a Linux x86-64 host with Git, Bash and an authorized Docker engine, run the
following from a checkout of this revision.

```sh
bash cases/portable-python/docker/build.sh
bash cases/portable-python/docker/check.sh > slurm-test.json
```

The [Docker recipe](cases/portable-python/SLURM.md#reproduce-from-a-clean-checkout)
describes the inputs, package versions, limits and expected receipt.
The [MPI heat stencil](cases/mpi-stencil/README.md) uses the same pilot to
compare one, two and four processes on four physical cores at CIMAT.
The [LAMMPS copper simulation](cases/mpi-copper/README.md) measures parallel
scaling for a larger materials-science workload on that pilot.

## Job contract

A job describes a program, inputs, runtime, requested resources and expected
outputs. A saved recipe is a convenient way to repeat that description. The
institutional profile supplies the authorized execution route and resource
limits. The scheduler or worker runs the job. HPC MCP returns the job
identity, observed state and artifact references. A client can use the same
interface with its own program and data.

The [copper temperature sweep](cases/mpi-copper/TEMPERATURE_SWEEP.md) shows
an agent preparing new jobs from an operator-approved recipe and reading
their verified JSON results.

## Current stage

The [job](schemas/job-v1.json) and [result](schemas/result-v1.json) schemas cover
synchronous Python jobs on trusted Linux profiles. A portable job ran via CLI
and MCP on a local worker and an authorized CIMAT SSH profile. The
[Slurm profile](cases/portable-python/SLURM.md) also ran the job in a development
cluster and in a Docker development instance hosted at CIMAT. Both verified
recovery after interruption.
The independent workload passed in Codex and [Hermes
Agent](cases/portable-python/HERMES.md). Hermes also verified
[cancellation of a running MPI job](cases/mpi-copper/CANCELLATION.md).
The [master record](MASTER_TEST_RECORD.md) links the observations.
The catalog verifier needs Python 3.10 or later and the standard library.

```sh
python tools/validate_inventory.py
```

Original project material is offered under [MIT](LICENSE). See
[how to contribute](CONTRIBUTING.md).
