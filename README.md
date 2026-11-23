# Polisplexity HPC MCP

Open project for letting MCP-capable clients prepare, submit, track and recover
versioned scientific jobs on high-performance computing infrastructure.

Start with the [integration inventory](docs/INVENTORY.md), the first
[CIMAT/Guanajuato case](cases/cimat-guanajuato/README.md) and
[the architecture proposal](docs/rfc/0001-hpc-job-contract.md).
[The master record](MASTER_TEST_RECORD.md) distinguishes access evidence from
MCP execution evidence.

A scientific recipe selects the program and inputs. The institutional
profile supplies the authorized execution route and resource limits. The
scheduler or bounded worker runs the job, and MCP returns the job identity,
state and artifact references. OLDT Data Factory is the first workload.

## Current stage

Research inventory and bounded pilot. A fixed CPU probe ran both natively and
through MCP on the authorized CIMAT SSH profile. This release demonstrates one
synchronous operation and an identical numerical result. The city workload and
durable scheduler lifecycle are recorded as future pilot stages.
The catalog verifier needs Python 3.10 or later and the standard library.

```sh
python tools/validate_inventory.py
```

Original project material is offered under [MIT](LICENSE). See
[how to contribute](CONTRIBUTING.md).
