# Polisplexity HPC MCP

Open project for letting MCP-capable clients prepare, submit, track and recover
versioned scientific jobs on high-performance computing infrastructure.

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

## Job contract

A job describes a program, inputs, runtime, requested resources and expected
outputs. A saved recipe is a convenient way to repeat that description. The
institutional profile supplies the authorized execution route and resource
limits. The scheduler or worker runs the job. HPC MCP returns the job
identity, observed state and artifact references. A client can use the same
interface with its own program and data.

## Current stage

The [job](schemas/job-v1.json) and [result](schemas/result-v1.json) schemas cover
synchronous Python jobs on trusted Linux profiles. A portable job ran via CLI
and MCP on a local worker and an authorized CIMAT SSH profile. The
[Slurm profile](cases/portable-python/SLURM.md) also ran the job in a development
cluster and in a Docker development instance hosted at CIMAT. Both verified
recovery after interruption.
The independent workload passed in Codex and [Hermes
Agent](cases/portable-python/HERMES.md). The [master
record](MASTER_TEST_RECORD.md) links the observed results for each client.
The catalog verifier needs Python 3.10 or later and the standard library.

```sh
python tools/validate_inventory.py
```

Original project material is offered under [MIT](LICENSE). See
[how to contribute](CONTRIBUTING.md).
