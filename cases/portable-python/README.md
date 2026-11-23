# Portable Python job

This case submits a seeded prime-counting program and an input file from a
workspace. The verifier executes the program directly, checks the counts by
trial division, then compares the output bytes from the CLI and from an actual
MCP stdio session. The same session also submits a separate variance program.

## Run it

Run these commands from the repository root on Linux with Python 3.10 or later.

```sh
python -m hpc_mcp.client prepare --root cases/portable-python --manifest job.json
python -m hpc_mcp.client run --root cases/portable-python --manifest job.json
python -m pip install -r cases/cimat-guanajuato/requirements-mcp.txt
python -m tools.check_portable_job
```

For an authorized SSH target, configure an OpenSSH host alias out of band,
verify its host key, and authenticate before running the case. Set
`POLISPLEXITY_HPC_SSH_PROFILE` to that alias before using the CLI with
`--profile ssh`. The verifier accepts the alias as `--ssh-profile`. The remote
worker runs with the target's Python 3 and standard library.

To start the MCP server, set `POLISPLEXITY_HPC_JOB_ROOT` to a trusted
workspace and launch `python -m hpc_mcp.server` from the repository root.
`hpc_prepare` checks the manifest and input bytes. `hpc_run` takes the same
`manifest` path and `profile` and returns the completed job receipt. Both
tools resolve manifest and input paths inside the configured workspace.

## Contract

The [job schema](../../schemas/job-v1.json) describes the Python entrypoint,
argument vector, input digests, expected files and resource request. Programs
receive the declared arguments as tokens. Inputs are copied into a temporary
working directory. The worker also checks path relationships, reserves the
log file names, verifies input digests and applies profile-specific limits.

The [result schema](../../schemas/result-v1.json) identifies the manifest by the
SHA-256 of its compact, key-sorted JSON, and records a job UUID, native process ID,
runtime version, timing, child exit code, logs and artifact digests. A negative
exit code identifies a terminating POSIX signal. An exit of zero with an
unavailable expected file is `missing_outputs`. Artifact and log bytes travel
in the receipt as Base64 for files up to 256 KiB. Applications can verify data
independently against the receipt hashes.

The local profile caps requests at four CPUs, 512 MiB and 30 seconds. The SSH
profile caps requests at one CPU, 128 MiB and 15 seconds. The worker sets CPU
affinity, per-process limits and a wall timeout. Use the profiles for trusted
single-file Python programs and input data under the executing user's authority.
Per-process limits are distinct from scheduler allocations and process-tree
resource accounting. Each invocation launches a process and returns its receipt
on completion. Queue operations, retained server-side artifacts, cancellation
and safe retry after a lost response require durable backend state.

The [CIMAT SSH and local report](evidence/portable-20261123.json) covers the
reference output, normal completion, exit 7, a missing output despite exit 0,
a one-second timeout, rejection before launch, and the second program. It
covers direct SSH execution and MCP over local stdio. The
[Slurm case](SLURM.md) uses the same workload and exercises queued submission
and recovery.
