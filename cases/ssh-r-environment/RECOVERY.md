# Recover a Docker R job after a lost MCP response

Hermes submits a trusted R manifest with a caller-generated request UUID
and the prepared environment ID. The managed SSH profile records the
manifest, environment and dispatch intent in private node storage before it
creates or starts the Docker container.

`hpc_ssh_submit` returns the request UUID and the native container ID.
Repeating the request reconciles the recorded intent and the Docker state.
A changed manifest or environment with the same UUID is rejected.
`hpc_ssh_status` can find a job by UUID in a new MCP session. On exit it
records the observed native result, stores declared artifacts by reference
and removes the finished container after persisting the receipt. An intent
without confirmed execution reports `unknown` and remains available for
reconciliation. [Docker container state](https://docs.docker.com/reference/cli/docker/inspect)

The detached route supports the approved Docker R runtime and referenced
outputs. It uses the existing job CPU, memory and file limits. The image
provides GNU `timeout` for the requested wall time. The original request
and result are stored in `jobs/<request UUID>/` under the configured SSH
data root. [GNU timeout](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html)

## Repeat the CIMAT test

Use this checkout with the [Hermes and SSH setup](../../INSTALL.md).
Set the SSH alias and use fresh private environment and data directories.
Seed the synthetic data on the node and run the following from the
checkout. Use a new output directory for each run.

```sh
python -m tools.run_hermes_r_storage --seed-dataset
python -m tools.run_hermes_ssh_recovery --output runs/ssh-recovery
python -m tools.run_hermes_ssh_recovery --verify-only --output runs/ssh-recovery
```

The runner opens separate Hermes profiles and MCP sessions. For the first
session the trace relay waits for the successful native submit reply, logs
it as `dropped_response`, and closes the MCP connection before delivery.
The second session retries the same UUID, consults its status and downloads
the stored CSV with `hpc_fetch_artifact`.

A separate event observer on the SSH host subscribes before the submit. It
filters on the request label and checks for one Docker create, one start
and one successful exit. The verifier reads the actual downloaded client
file, checks its SHA-256 against the stored reference and compares it with
an independent CSV calculation. [Docker events](https://docs.docker.com/reference/cli/docker/system/events/)

## CIMAT acceptance on November 24, 2026

Docker accepted request `dc00f5ae-7e9b-494e-8773-bc92cc774af3`. The trace
relay dropped the submit reply before it reached Hermes. A second session
retried the same request and queried its status. Docker recorded exactly
one container creation, one start, a successful exit and the removal of
that container.

Hermes recovered the 1,146,924-byte CSV by reference. Its SHA-256,
`1e551cb2446e45841a65fb51a6e7c8788df175cc7ed9422c1e0f4dc5bdb8e4e3`,
matched the independently measured file on CIMAT and the expected CSV.
The published trace redacts the account's transient free disk figure.
[Submit and dropped response](evidence/cimat-recovery-20261124/submit/mcp.jsonl) · [Recovery and download trace](evidence/cimat-recovery-20261124/recover/mcp.jsonl) · [Verification and Docker events](evidence/cimat-recovery-20261124/record.json)

Additional MCP checks rejected an unknown request and a changed manifest
under the original UUID. A separate detached process reached its wall
limit and returned Docker exit code 137 without publishing an artifact.
