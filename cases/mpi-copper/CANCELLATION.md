# Cancel a running MPI job with Hermes Agent

Hermes Agent 0.18.2 with Claude Sonnet 4.6 prepared and submitted a
131,072-atom LAMMPS copper job on two MPI ranks in the CIMAT Docker pilot.
It observed Slurm `RUNNING`, called `hpc_slurm_cancel` and polled until
accounting reported `CANCELLED`. A second cancellation with the same UUID
returned the same terminal response. A separate, unregistered UUID was
rejected. The trace contains the actual agent's tool calls and replies.
[MCP trace](evidence/cimat-hermes-mpi-cancel-20261124.jsonl) · [Verified record](evidence/cimat-hermes-mpi-cancel-20261124.json)

A read-only observer independently saw the MPI launcher and two LAMMPS
processes while the allocation was running. The queue was empty for that
allocation after cancellation and the observer saw zero remaining MPI
processes. Native accounting recorded one cancelled allocation using two
CPUs. The worker had produced no successful output receipt. [Slurm job states](https://slurm.schedmd.com/job_state_codes.html)

## Reproduce

Start with the [copper image](README.md#reproduce). Build the cancellation
overlay from a committed checkout. It reuses the isolated Docker scheduler
and the existing MPI workload.

```sh
revision=$(git rev-parse HEAD)
image=polisplexity-hpc/mpi-cancel:local
git archive "$revision" hpc_mcp cases/mpi-copper/docker/Dockerfile.cancel \
  tools/audit_slurm_cancel.py tools/check_slurm_job.py |
  docker build --file cases/mpi-copper/docker/Dockerfile.cancel \
    --label "org.opencontainers.image.revision=$revision" --tag "$image" -
```

Generate distinct request UUIDs for the allocation and the unknown-UUID
probe. Select two physical cores for the existing Docker recipe. In a test
Hermes profile with a configured model, connect only the four lifecycle
tools shown below. Use absolute, fresh trace and audit paths. Replace the
checkout paths, CPU IDs and job UUID in this example.

```yaml
mcp_discovery_timeout: 45
tools:
  tool_search:
    enabled: "off"
mcp_servers:
  polisplexity_hpc:
    command: python3
    args:
      - /checkout/hpc-mcp/tools/trace_mcp.py
      - --trace
      - /test-run/mcp.jsonl
      - --
      - bash
      - -c
      - 'log=$1; shift; exec "$@" 2>"$log"'
      - audit-transport
      - /test-run/backend.log
      - env
      - POLISPLEXITY_SLURM_TEST_CPUS=2
      - POLISPLEXITY_SLURM_TEST_CPUSET=0,1
      - bash
      - /checkout/hpc-mcp/cases/portable-python/docker/check.sh
      - polisplexity-hpc/mpi-cancel:local
      - /opt/polis-venv/bin/python
      - -m
      - tools.audit_slurm_cancel
      - "<job-uuid>"
    connect_timeout: 45
    timeout: 20
    tools:
      include: [hpc_prepare, hpc_slurm_submit, hpc_slurm_status, hpc_slurm_cancel]
      resources: false
      prompts: false
```

Ask the agent to prepare `mpi-copper-cancel.json` with profile `slurm` and
submit it once under the job UUID. Ask it to observe `RUNNING`, cancel the
job, and verify `CANCELLED` via status. Then have it retry cancellation
of the job and probe the unregistered UUID. Request one JSON object with
`state`, `native_state`, `native_id` and `native_exit_code` from the
confirmed result. The task uses only those four MCP tools.

The observer emits a JSON object after the `CANCEL_AUDIT` prefix on
backend stderr. To verify a fresh run, make a JSON file with that object
under `audit` and the two UUIDs under `request_id` and
`unknown_request_id`. Pass it to the verifier with the trace and agent
answer. The checked-in record includes the structured answer.

```sh
trace=cases/mpi-copper/evidence/cimat-hermes-mpi-cancel-20261124.jsonl
record=cases/mpi-copper/evidence/cimat-hermes-mpi-cancel-20261124.json
python3 -m tools.verify_agent_cancel --trace "$trace" --answer "$record" --run "$record"
```
