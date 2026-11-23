# First dependency review and issue drafts

Proposed · 2026-11-23.

This review narrows the [integration inventory](../INVENTORY.md) to the
dependencies for the first general-purpose job. Its companion
[RFC](../rfc/0001-hpc-job-contract.md) defines the project boundary. The tests
below are proposed unless described as observed.

## Source and reuse review

| Candidate | Source and interface | Observed evidence | Proposed decision and remaining check |
|---|---|---|---|
| Silogen HPC MCP | MIT. [Reviewed source revision](https://github.com/silogen/hpc-assistant/tree/a50091fd99cd71b5aae22b4c07c9b286766f2207/hpc-mcp). The server exposes preflight, submit, queue, accounting, cancellation and scoped file operations. | A local stdio facade delegated file reading to the source server, matched the fixture SHA-256 and rejected an unknown artifact ID. | Evaluate as the first Slurm provider. Compare its native job receipt and artifact with direct Slurm execution. Check reconciliation following a lost submit response and record the limits of the selected status interfaces. |
| Purdue cluster-mcp | The README declares MIT. [Reviewed source revision](https://github.com/PurdueRCAC/cluster-mcp/tree/aab45a3adeed09c7de9f976fb4968f4d60ce972f). Its core and Slurm capability are installable separately. | Source reviewed. The reviewed client package requires Python 3.14. The standalone license text was absent from the reviewed tree. | Compare as an alternative provider on the same case. Confirm the upstream notices before copying code. Record the transport and runtime setup implied by each provider. |
| PSI/J | MIT. [Tested Python release](https://pypi.org/project/psij-python/0.9.11/) and [job specification](https://exaworks.org/job-api-spec/specification.html). It supplies a job model, native identifiers and executor interfaces. | The local executor ran an unfamiliar Python program and preserved an ordinary failure code. Reattaching to an externally supervised local process reported exit 0 although the supervisor observed exit 7. | Reuse its vocabulary where it fits. Validate recovery using a trustworthy terminal receipt; preserve the unknown state when evidence is unavailable. Evaluate scheduler implementations independently of the local reattachment result. |
| ReFrame | BSD-3-Clause. [Release 4.11.0](https://github.com/reframe-hpc/reframe/releases/tag/v4.11.0) and [reporting CLI](https://reframe-hpc.readthedocs.io/en/stable/manpage.html#options-controlling-reframe-output). It supplies sanity checks, performance checks and structured reports. | Source and documented CLI reviewed. An HPC MCP run using ReFrame remains pending. | Evaluate as a verifier for an admitted workload. Preserve the native report and extract its scoped assertions. Confirm that the proposed invocation represents the intended scheduler, workload and timing. |

The [master test record](../../MASTER_TEST_RECORD.md) remains the reference
for project admission. The CIMAT CPU receipt verifies the bounded SSH
fixture. The local research observations above apply to their described
operations and environments.

The [Slurm development case](../../cases/portable-python/SLURM.md) compares
the pinned Silogen provider with the native scheduler. Silogen's queue output
truncates job names and its accounting tool queries by a known job ID or a
time window. Polisplexity uses the native Slurm interfaces for exact request
reconciliation when a client has yet to receive a job ID.

## Proposed issues in order

### 1. Version the specification and admit a general-purpose fixture

Define the initial job manifest and result receipt. Include program and
runtime identities, typed arguments, input hashes, resource request, expected
files, backend identity, native job identifier, exit evidence and output
hashes. Begin with a small seeded Python program submitted from a clean
workspace. Separate its parameter input from its source. Compare all
structured outputs with an independent native reference and include a
deterministic failing invocation. The same manifest must support a new
program package supplied by the caller.

Acceptance evidence consists of a public fixture, its reference outputs,
valid and rejected manifest examples, and an exact description of which
fields are portable across SSH and Slurm.

### 2. Exercise the same specification on SSH and Slurm

Use the existing CIMAT SSH route for the bounded direct case, and an
authorized lab Slurm profile for the scheduled case. Check preflight,
submit, status, terminal evidence and artifact retrieval. Compare direct
execution, the original provider where applicable, and actual HPC MCP calls.
Keep the target-specific limits and status visible.

Acceptance checks include refusal before launch, ordinary nonzero exit,
a lost response after a submit the backend accepted, and a fresh client
recovering the same job and its artifacts. Record the ambiguous state when
the backend cannot reconcile acceptance. Distinguish queue and transfer
times from execution time where the profile reports them.

### 3. Add a reproducible verification run and agent observations

Evaluate the first ReFrame check on the admitted workload. Save its report
with the native comparator and the artifacts it verified. Include a wrong
result or missing file to prove that verification catches it. Run the same
versioned task in fresh Codex and Hermes workspaces. Preserve execution
evidence, structured claims and narrative review separately in the master.

## Review decisions

- Agree on the minimum job and result fields, and on provider-specific fields
  that need namespacing.
- Choose the first Slurm environment and decide whether Silogen or another
  provider best supports the recovery check on that environment.
- Keep general execution acceptance scoped to this workload and the tested
  profiles. Purpose-specific Urban MCP and Quantum MCP API bindings can use
  the same contracts and receive their own case reviews.
