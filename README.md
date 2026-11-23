# Polisplexity HPC MCP

Open project for letting MCP-capable clients prepare, submit, track and recover
versioned scientific jobs on high-performance computing infrastructure.

Start with the [integration inventory](docs/INVENTORY.md), the
[CIMAT connectivity pilot](cases/cimat-guanajuato/README.md) and
[the portable Python case](cases/portable-python/README.md).
[RFC 0001](docs/rfc/0001-hpc-job-contract.md) proposes the broader interface.
[The master record](MASTER_TEST_RECORD.md) distinguishes access evidence from
MCP execution evidence.

A job describes a program, inputs, runtime, requested resources and expected
outputs. A saved recipe is a convenient way to repeat that description. The
institutional profile supplies the authorized execution route and resource
limits. The scheduler or worker runs the job. HPC MCP returns the job
identity, observed state and artifact references. A client can use the same
interface with its own program and data.

## Current stage

The [job](schemas/job-v1.json) and [result](schemas/result-v1.json) schemas cover
synchronous Python jobs on trusted Linux profiles. A portable job ran via CLI
and MCP on a local worker and an authorized CIMAT SSH profile. Queued submission,
status recovery after a disconnect and scheduler accounting are future stages.
The catalog verifier needs Python 3.10 or later and the standard library.

```sh
python tools/validate_inventory.py
```

Original project material is offered under [MIT](LICENSE). See
[how to contribute](CONTRIBUTING.md).
