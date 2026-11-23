# Polisplexity HPC MCP

Open project for letting MCP-capable clients prepare, submit, track and recover
versioned scientific jobs on high-performance computing infrastructure.

Start with the [integration inventory](docs/INVENTORY.md), the
[CIMAT connectivity pilot](cases/cimat-guanajuato/README.md) and
[the architecture proposal](docs/rfc/0001-hpc-job-contract.md).
[The master record](MASTER_TEST_RECORD.md) distinguishes access evidence from
MCP execution evidence.

A job describes a program, inputs, runtime, requested resources and expected
outputs. A saved recipe is a convenient way to repeat that description. The
institutional profile supplies the authorized execution route and resource
limits. The scheduler or worker runs the job. HPC MCP returns the job
identity, observed state and artifact references. The next acceptance case
uses a new general-purpose workload. OLDT Data Factory remains an applied case.

## Current stage

Research inventory and bounded pilot. A fixed CPU probe ran both natively and
through MCP on the authorized CIMAT SSH profile. This release demonstrates one
synchronous operation and an identical numerical result. The portable job
contract, durable scheduler lifecycle and applied cases are proposed stages.
The catalog verifier needs Python 3.10 or later and the standard library.

```sh
python tools/validate_inventory.py
```

Original project material is offered under [MIT](LICENSE). See
[how to contribute](CONTRIBUTING.md).
