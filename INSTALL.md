# Install HPC MCP v0.1.0-alpha.3

The SSH acceptance test starts with node discovery and ends with a verified
CSV on the client. Use a Linux client with Git, Python 3.10 or later,
`venv`, OpenSSH and a working Hermes CLI. Configure a model in Hermes's
usual profile. The runner creates a separate temporary Hermes profile and
MCP server for each session. [Hermes setup](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart) · [Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)

Use an authorized Linux SSH account that permits direct execution and has
Python 3.10 or later. The example uses a compatible native R 4.5.2
installation or the pinned Linux amd64 Rocker image. The Docker route
requires access to the node's local Docker daemon and registry access if the
image needs to be pulled. Use your own SSH alias with a trusted host key.

## Set up a clean checkout

```sh
git clone --branch v0.1.0-alpha.3 --single-branch https://github.com/polisplexity/hpc-mcp.git
cd hpc-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r cases/cimat-guanajuato/requirements-mcp.txt \
  -r cases/mpi-copper/requirements-hermes-test.txt
hermes --version
```

Use `--hermes` to specify the CLI executable or `--hermes-home` to select a
configured Hermes profile when you run the test.

## Discover the node, save the result and retrieve it by reference

Replace `your-authorized-ssh-alias` with the alias for your account. These
commands create fresh, private directories on the node and generate the
synthetic CSV there. Use a new output directory for each acceptance run.

```sh
export POLISPLEXITY_HPC_SSH_PROFILE=your-authorized-ssh-alias
POLISPLEXITY_HPC_SSH_ENV_ROOT=$(ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes \
  "$POLISPLEXITY_HPC_SSH_PROFILE" 'umask 077; mktemp -d "$HOME/.hpc-mcp-env.XXXXXXXX"')
POLISPLEXITY_HPC_SSH_DATA_ROOT=$(ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes \
  "$POLISPLEXITY_HPC_SSH_PROFILE" 'umask 077; mktemp -d "$HOME/.hpc-mcp-data.XXXXXXXX"')
export POLISPLEXITY_HPC_SSH_ENV_ROOT POLISPLEXITY_HPC_SSH_DATA_ROOT
python -m tools.run_hermes_r_storage --seed-dataset
python -m tools.run_hermes_r_download --output runs/alpha3
```

The first Hermes session calls `hpc_environment_probe`, prepares the
approved R runtime and runs the job against the dataset on the node. The
second starts from the saved artifact reference and calls
`hpc_verify_artifact` and `hpc_fetch_artifact`. The runner rehashes the
actual client file and checks it against an independent CSV calculation.
Expect 65,536 data rows and 1,146,924 bytes. The expected SHA-256 and client
filename are `1e551cb2446e45841a65fb51a6e7c8788df175cc7ed9422c1e0f4dc5bdb8e4e3`.

Open the CSV in `runs/alpha3/download/`. The run also writes
`save/mcp.jsonl`, `fetch/mcp.jsonl` and `record.json`. Recheck the
recorded exchanges and digest with:

```sh
python -m tools.run_hermes_r_download --verify-only --output runs/alpha3
```

[R case and storage details](cases/ssh-r-environment/STORAGE.md#recover-a-large-output-from-another-hermes-session)

## Slurm and Docker copper pilot

The Docker installation builds a single-node Slurm pilot with Open MPI,
LAMMPS and the copper recipe. Use a Linux x86-64 Docker engine reachable
from a Linux shell with Git, Bash and Python 3.10 or later. The build
downloads pinned Debian packages and Python dependencies. The test uses
two CPU IDs and one GiB of container memory.

Install Hermes on the host and configure an API-key-backed model in its
usual profile. The test uses that profile's model and provider settings
in a temporary profile. The default source is `~/.hermes`, or the directory
selected by `HERMES_HOME`. [Hermes setup](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart) · [Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)

### Build the alpha.2 copper case

```sh
git clone --branch v0.1.0-alpha.2 --single-branch https://github.com/polisplexity/hpc-mcp.git
cd hpc-mcp
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
hermes --version
bash cases/mpi-copper/docker/build-sweep.sh
```

Expect `linux/amd64` from the Docker check. The build leaves the image
`polisplexity-hpc/mpi-sweep:local` with the checkout's exact Git revision
as an OCI label. The build uses committed source from that revision.

### Run the copper acceptance test

On the Docker host, use `lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE` to select two
online logical CPU IDs on distinct physical cores in the same NUMA node.
Replace `0,2` below with those IDs. From the checkout on the Hermes host,
run the test and give it a new output directory each time.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r cases/mpi-copper/requirements-hermes-test.txt
python -m tools.run_hermes_copper_sweep --cpu-ids 0,2 --output runs/copper-alpha2
```

The test launches the local Hermes CLI, exposes the six HPC MCP tools and
asks Hermes to discover the recipe, prepare and run 300, 600 and 900 K
jobs, repeat the 300 K submission, and retrieve all three results. The
runner checks the agent's answer against the actual MCP exchanges, checks
for exactly three allocations in Slurm, and compares the thermodynamic
samples with three direct LAMMPS runs.

On success, the command prints the verified comparison. The output
directory contains `mcp.jsonl`, `record.json`, the agent's answer, the direct
reference data and diagnostic logs. To verify the recorded run again:

```sh
python -m tools.verify_agent_copper_sweep \
  --trace runs/copper-alpha2/mcp.jsonl --answer runs/copper-alpha2/agent.txt \
  --record runs/copper-alpha2/record.json
```

Use `--hermes-home` to select a different configured profile directory or
`--hermes` to specify a Hermes executable. The test starts its Slurm
daemons in a disposable container on an internal Docker network. Hermes
uses its configured model from the host. The tested combination is
Hermes Agent 0.18.2 and Claude Sonnet 4.6. [Scientific case and evidence](cases/mpi-copper/TEMPERATURE_SWEEP.md)

If Docker reports that its default address pools have been fully subnetted,
repeat the test with an unused IPv4 CIDR on the Docker host and a fresh
output directory. Replace the example range if it overlaps an existing route
or Docker network.

```sh
python -m tools.run_hermes_copper_sweep --cpu-ids 0,2 \
  --subnet 10.237.44.0/28 --output runs/copper-alpha2-subnet
```

If a run fails, inspect `hermes.stderr` for the model invocation,
`backend.stderr` for Docker and Slurm, and `native.stderr` for the direct
comparison, when present. The runner exits unsuccessfully if any required
evidence is missing or disagrees.

## Run the server on an existing Linux profile

For local, SSH and site-configured Slurm use, run the module from the
checkout in a Python environment with the MCP dependency.

```sh
python -m pip install -r cases/cimat-guanajuato/requirements-mcp.txt
export POLISPLEXITY_HPC_JOB_ROOT="$PWD/cases/portable-python"
python -m hpc_mcp.server
```

Configure the same launch command in the MCP client. Use the documented
workspace and authorized connection settings for each profile.
[Local and SSH configuration](cases/portable-python/README.md) · [Slurm configuration](cases/portable-python/SLURM.md#configure-an-approved-allocation) · [Managed SSH environments](cases/ssh-environment/README.md) · [R via SSH and Docker](cases/ssh-r-environment/README.md)
