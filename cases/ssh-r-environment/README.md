# Run a prepared R environment on an SSH account

Hermes can inspect an authorized account, prepare a compatible R environment,
and execute a trusted R manifest. The example sums eight synthetic order rows
by region and returns a JSON artifact with integer cent amounts.

| Tool | R behavior |
| --- | --- |
| `hpc_environment_probe` | Report native `Rscript` detection and version, the approved image digest and whether it is cached. |
| `hpc_environment_prepare` | Reuse native `Rscript` if its version matches the approved lock. Otherwise inspect or pull the locked image for the configured platform and return an environment ID. |
| `hpc_environment_run_batch` | Run the trusted `rscript` manifest after checking the expected environment ID from preparation. Docker execution uses the local cached digest and reports the container's observed image identity and exit code. |

The operator controls the SSH alias, private account directory, workspace and
environment locks. The included lock pins the Linux amd64 image manifest of
Rocker R 4.5.2. The job uses R base packages. Native R runs under the worker's
POSIX limits. Docker uses the account's local Unix socket, a non-root
container user, a read-only container root, no network and a single temporary
host mount for the staged job. The job requests one CPU, 512 MiB and a
15-second wall limit. Inline inputs and artifacts are capped at 256 KiB each.
[Rocker image documentation](https://rocker-project.org/images/versioned/r-ver) · [Docker container options](https://docs.docker.com/reference/cli/docker/container/run/)

Each repeat creates a new job. The selected native installation or cached
image is reused. The Docker path removes its job containers and retains the
approved image.

## Reproduce with Hermes

Use an authorized SSH alias with the host key already trusted, remote Linux
Python 3.10 or later, and either compatible native R or an authorized local
Docker daemon. Image preparation requires registry access when the image is
absent. Configure a working Hermes model on the client.
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
python -m tools.run_hermes_r --output runs/ssh-r-environment
```

The runner prepares the client workspace, supplies the job path to Hermes
and records the agent's actual tool calls. It verifies runtime selection,
reuse, the two native execution IDs and the agent answer. A Python CSV
reference checks the complete JSON result and repeated artifact hashes.

```sh
python -m tools.run_hermes_r --verify-only --output runs/ssh-r-environment
```

Review any trace before sharing it. Keep the connection configuration and
diagnostic logs private.

## CIMAT acceptance on November 24, 2026

Hermes probed the assigned SSH account and found no native `Rscript`. Its
first preparation pulled the approved Rocker image. The first launch after
the pull returned no verified receipt. A repeat on the cached image returned
the expected artifact. The initial trace preserves that sequence.
[Initial pull and first launch trace](evidence/cimat-hermes-20261124/cold-mcp.jsonl)

The verified run confirmed exit status with Docker directly. Hermes repeated
the complete prepare-and-run sequence twice, using the cached image and the
same environment ID. Both jobs produced the same bytes. R 4.5.2 processed
eight order rows and returned 50,190 total cents, with 19,900 for centro,
14,500 for norte and 15,790 for sur. Separate Docker event reads confirmed
that both containers started, exited 0 and were removed, and that the pinned
image remained cached.
[Verified MCP trace](evidence/cimat-hermes-20261124/mcp.jsonl) · [Result record](evidence/cimat-hermes-20261124/record.json) · [Docker audit](evidence/cimat-hermes-20261124/docker-audit.json)

Additional MCP checks rejected a mismatched environment ID and distinguished
an R process exiting 7 from a wall-time timeout. The public traces redact
the transient free disk figure.
