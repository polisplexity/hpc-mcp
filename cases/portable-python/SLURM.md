# Queue the portable Python job with Slurm

The Slurm profile uses the same [job manifest](job.json) and
[result receipt](../../schemas/result-v1.json) as the direct Python runner.
Slurm allocates one node and one task. The Python worker checks the requested
CPU affinity, address-space ceiling and wall timeout before returning the
child's exit code and artifact bytes.

## Configure an approved allocation

Run the server under the authorized account on a Linux login host with
`sinfo`, `sbatch`, `squeue` and `sacct`. The configured state directory
must have mode `0700`, be owned by the account, and be shared with compute
nodes at the same absolute path. Use a separate directory for each cluster and
an approved partition with available job accounting. The profile assumes a
single cluster and supports single-task jobs without arrays.

```sh
export POLISPLEXITY_HPC_JOB_ROOT="$PWD/cases/portable-python"
export POLISPLEXITY_HPC_SLURM_STATE="$HOME/.local/state/polisplexity-hpc/cluster-a"
export POLISPLEXITY_HPC_SLURM_PARTITION="<approved-partition>"
export POLISPLEXITY_HPC_SLURM_ACCOUNT="<approved-account>"
python -m pip install -r cases/cimat-guanajuato/requirements-mcp.txt
python -m hpc_mcp.server
```

Set the account variable when the site requires it. Set
`POLISPLEXITY_HPC_SLURM_PYTHON` to a site-approved absolute interpreter path
if the compute node uses a different path from `/usr/bin/python3`. Profile
settings and the state directory stay outside version control.

## Submit and recover

1. Call `hpc_slurm_preflight` to check client availability and whether the
   configured partition is visible. Visibility alone does not establish
   authorization to submit.
2. Call `hpc_prepare` with the manifest path and `profile: "slurm"` to inspect
   the job identity and resource request. Call `hpc_slurm_submit` with the path and a
   client-generated `request_id` UUID. Retain the UUID across reconnections.
   The first submit stores its intent before contacting Slurm. If an
   acknowledgment arrives, the tool returns the native job ID.
3. Call `hpc_slurm_status` with that UUID from the same or a fresh client.
   It looks for the exact recorded job name in the user's `squeue` and
   `sacct` records. A terminal result includes the worker receipt after
   verifying the ID, exit code and hashes against the staged job.

Reusing a UUID for the same job reconciles the first attempt. The server
refuses a different manifest under that UUID. If available scheduler records
cannot establish what happened, the state remains `unknown` and retrying
with that UUID does not enqueue another job. Keep the state directory and
the scheduler's accounting record available for recovery. An operator
should reconcile an unknown request before choosing a new UUID.

Scheduler timestamps are returned as reported by `sacct`. They give the
submit, start and end times, plus elapsed run time where available. Job
files use the shared filesystem. The profile does not measure transfer time.

## Reproduce from a clean checkout

Check out the GitHub release or PR revision that contains this case. On an
authorized Linux x86-64 Docker host, run the build and check from that
checkout. The build sends a list of files committed at `HEAD` to Docker.
It uses the Debian base image digest and signed package snapshot in
the [Docker files](docker/), Slurm 26.05.5 and the recorded Python dependency
versions. The build needs access to Docker Hub, Debian Snapshot and PyPI.
Git, Bash and GNU `timeout` provide the host-side commands.

```sh
bash cases/portable-python/docker/build.sh
bash cases/portable-python/docker/check.sh > slurm-test.json
```

The check starts one test node with MUNGE and MariaDB-backed accounting.
Docker bounds the container to one CPU and 1 GiB on a temporary internal
network. The container uses its own files and publishes zero host ports.
The test report goes to stdout and diagnostics go to stderr. On exit, the
check removes the container and network and keeps the built image for reuse.

Compare the report's native SHA-256 with the MCP receipt and the recovered
artifact. The report should show exit `7:0` for the intentional failure,
`unknown` when acceptance is unconfirmed, and one allocation for the shared
request in `concurrent_requests`. A distinct request gets its own allocation.
Slurm IDs, request UUIDs and timestamps vary from run to run. The container's
accounting and job files live for the duration of that run.

The [clean GitHub checkout receipt](evidence/slurm-github-recipe-20261123.json)
records the tested source revision, Docker 29.4.1, Python 3.14.10 and the
matching native, MCP and recovered artifact hashes from a build at CIMAT.

## Verify a new workload from an MCP client

Configure an MCP stdio server with the command below. Use an absolute path to
the checkout when the client starts in a separate workspace.

```sh
bash cases/portable-python/docker/check.sh polisplexity-hpc/slurm-test:local \
  /opt/polis-venv/bin/python -m hpc_mcp.server
```

Ask the client to prepare `client-example/job.json` with profile `slurm`,
submit the job with a new request UUID, and retrieve its verified result
using the same UUID. The program fits a line to six synthetic points. Its
intercept is `76/21` and its slope is `94/35`, derived independently from the
two normal equations. Compare the result artifact and its digest with a direct
run of `fit.py`. Record the client version, native job ID, receipt and final
answer as separate observations.

The [client receipt](evidence/slurm-clients-20261123.json) confirms the
Codex result and direct Hermes MCP dispatch. Codex required an explicit
authorization for the three test tools in the unattended session. The Hermes
agent trial failed verification because its completion claims had no matching
tool exchanges. Follow [issue #6](https://github.com/polisplexity/hpc-mcp/issues/6)
for agent acceptance.

## Reproduce the comparison

```sh
python -m tools.check_slurm_job --out result.json
```

The verifier compares native `sbatch` with actual MCP calls, checks exit
code 7 and rejected partition and account examples, and terminates its own
test server around the submission boundary. When Slurm accepted the request, a fresh client
recovers the result and verifies that accounting contains exactly one
allocation. A fault before submission is exercised separately. Two independent
MCP clients also submit the same request concurrently. The verifier checks
that accounting contains one allocation for their shared UUID, a separate
allocation for a new UUID using the same manifest, and that a conflicting
manifest for the first UUID is rejected.

The verifier can compare the optional Silogen MCP provider from a separate
virtual environment. Install the reviewed revision in that environment
before passing its interpreter.

```sh
python -m venv /path/to/silogen-venv
/path/to/silogen-venv/bin/pip install \
  "git+https://github.com/silogen/hpc-assistant.git@a50091fd99cd71b5aae22b4c07c9b286766f2207#subdirectory=hpc-mcp"
python -m tools.check_slurm_job --silogen-python /path/to/silogen-venv/bin/python
```

The [recorded development run](evidence/slurm-lab-20261123.json) used
Ubuntu Base 24.04.5 in WSL2 with Slurm 23.11.4, one compute node, MUNGE and
MariaDB-backed `slurmdbd`. The lab used Linux process tracking and Slurm's
development cgroup configuration without systemd. The
[CIMAT Docker development run](evidence/slurm-cimat-docker-20261123.json)
used Slurm 26.05.5 on an internal Docker network with a one-CPU and 1 GiB
container limit.

The [site scheduler qualification issue](https://github.com/polisplexity/hpc-mcp/issues/3)
records the checks for a future workload that requires a site-managed queue.
