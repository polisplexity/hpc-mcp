# Inspect and prepare an SSH compute account

HPC MCP connects to an existing Linux account, inventories visible resources,
and prepares an isolated Python environment from approved wheel versions. The
acceptance case summarizes three synthetic CSV files with DuckDB. It runs as a
bounded batch directly over SSH. [DuckDB release and wheel hashes](https://pypi.org/project/duckdb/1.4.5/)

| Tool | Contract |
| --- | --- |
| `hpc_environment_probe` | Read the configured SSH target's OS, Python, CPU affinity, visible RAM, storage, command availability, Docker daemon version and compute device indicators. List approved environments and any readiness records. Report account allocation and quota as unverified. |
| `hpc_environment_prepare` | Select a named lock from `environments/<name>.json` in the operator workspace. Verify wheel hashes during installation. Recheck package versions and return a stable installation ID on reuse. |
| `hpc_environment_run_batch` | Run one to four distinct workspace manifests sequentially with the prepared interpreter. Return a job receipt and any small JSON outputs for each manifest. |

The current `ssh-env` profile caps each process at one CPU, 1,024 MiB of
virtual address space and 15 seconds of wall time. Each inline file is capped
at 256 KiB. The DuckDB fixture uses one application thread and a 24 MB
DuckDB buffer memory setting. The address-space limit is a process limit.
It does not report physical memory consumed or a site allocation.

Use the profile where the provider permits direct execution. Only the operator
can configure the destination and private environment directory or add a lock
and trusted executable manifests to the workspace. The installer uses PyPI
wheels with pinned hashes and works inside the selected account directory.
Lock transitive dependencies explicitly. Concurrent prepare and batch
operations in the same directory return busy. A failed job returns its own
receipt. A broken connection can leave the state of a batch unknown. The Slurm
profile covers durable submission and reconciliation. [Slurm profile](../portable-python/SLURM.md)

## Repeat the Hermes test

Use an authorized SSH alias with an existing known host key. The fixture
supports Linux x86-64 with glibc 2.26 or later and CPython 3.10 through 3.13.
The remote Python must support `venv` with pip bootstrapping, and the account
must be able to download the approved wheel. On the client, configure a
working Hermes model and run the following from the checkout.
[Hermes setup](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart)

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r cases/cimat-guanajuato/requirements-mcp.txt \
  -r cases/mpi-copper/requirements-hermes-test.txt
export POLISPLEXITY_HPC_SSH_PROFILE=approved-host
POLISPLEXITY_HPC_SSH_ENV_ROOT=$(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
  "$POLISPLEXITY_HPC_SSH_PROFILE" 'umask 077; mktemp -d "$HOME/.hpc-mcp-env.XXXXXXXX"')
export POLISPLEXITY_HPC_SSH_ENV_ROOT
python -m tools.run_hermes_environment --output runs/ssh-environment
```

Use a new output directory and a fresh private remote directory for each
cold-install acceptance run. Keep the remote directory to reuse the same
environment in subsequent jobs. The runner copies the approved lock and
generates the manifests and synthetic inputs in a temporary client workspace.

The runner exposes the three environment tools to Hermes and captures the
actual MCP exchanges. Verification checks the first installation, the same
installation ID on reuse, six successful native process receipts, and the
agent's final answer. It recomputes the result of each partition independently
with Python's CSV reader and checks the returned artifact hashes.

```sh
python -m tools.run_hermes_environment --output runs/ssh-environment --verify-only
```

The trace contains the tools' results, including account capability fields
and job output. Review it before sharing and keep the backend diagnostics and
connection configuration private.

## CIMAT acceptance on November 24, 2026

Hermes ran the checks through HPC MCP over the assigned SSH account. It
installed DuckDB once, completed three jobs, reused the same installation
and completed the same three jobs again. The sums for 1,000, 2,000 and 3,000
rows were 48,941, 97,973 and 146,921. The verifier checked every returned
artifact against the independent calculation and compared both rounds.
[MCP trace](evidence/cimat-hermes-20261124/mcp.jsonl) · [Verified record](evidence/cimat-hermes-20261124/record.json)

The first test reached DuckDB installation and failed to start the jobs
under the 128 MiB virtual memory ceiling of the original SSH profile. An
independent probe reproduced the failure and completed the query from 768
MiB among the ceilings tested. The successful agent run used the 1,024 MiB
managed profile. Separate MCP checks rejected unapproved environment names
and over-budget jobs, and let the remaining jobs finish after one exited 7.
The published trace redacts the SSH account's transient free disk figure.
