# RFC 0001 · Portable scientific jobs

Proposed · revised 2026-11-23.

## Product boundary

A job describes an executable or program, its inputs, runtime, resource
requirements and expected outputs. It can be prepared from a new submission
or a saved recipe. An execution profile declares its submission path,
supported capabilities and output storage. The CIMAT pilot verified SSH
execution. Scheduler-backed profiles are evaluated separately.

HPC MCP owns the general-purpose HPC interface and its job, capability and
result contracts. A connector can call an upstream MCP or a native API/CLI
and maps only the needed operations. Scientific clients can use
purpose-specific API bindings to submit and collect their workloads. Urban
MCP and Quantum MCP are examples. Cross-product orchestration belongs to
the separately planned integration product.

## Proposed operations

- Discover authorized profiles and their observed capacities.
- Prepare a new or saved job from a manifest and requested resources.
- Record what the site, scheduler and a small execution probe verified.
- Submit a prepared job and retain both project and backend IDs.
- Read state and scoped logs, reconcile ambiguous submission, cancel owned work.
- Retrieve a verified result manifest and artifact references.

Keep native state, exit reason and array task IDs. Use an idempotency key
bound to the submitted job, inputs and parameters. Persist the dispatch
intent and reconcile uncertainty with backend evidence before retrying.
Record whether queue time and resource accounting are available. Keep
authentication, authorized storage and site-specific defaults in the local
profile. Describe a workload with typed arguments and explicit input, output
and runtime identities.

## Open development sequence

The [first dependency review and issue drafts](../research/first-dependency-review.md)
identify the candidate implementations, scoped evidence and acceptance cases
for this proposal.

1. Review each prioritized upstream capability. Record source revision,
   licensing, actual callable interfaces, overlap, reuse decisions, the
   smallest proposed addition and a concrete acceptance test. Start with
   Silogen for Slurm, Purdue as a comparison, PSI/J for the job model and
   ReFrame for repeatable checks. The CIMAT receipt and local research spikes
   establish separate, bounded observations.
2. Review this RFC and the critical inventory in an open PR. For each agreed
   capability, open an issue with its upstream dependency, scoped files,
   reproducible input, reference, failure cases and acceptance evidence.
3. Choose one unfamiliar general-purpose program and provide a clean,
   reproducible fixture. Run it natively, then through the original connector
   and through our public MCP interface. Compare results, rejected requests
   and recovery after an ambiguous submission. Test SSH and Slurm as
   distinct profiles. Treat measurement and validation as their own checks.
4. Run the same versioned task in fresh Codex and Hermes workspaces. Review
   artifacts, structured claims and final responses separately. Update the
   master record and case guide with source, input and output identity,
   observations, failures and the exact tested scope.
5. Invite an independent contributor to reproduce the portable workload on
   another available HPC environment before claiming broad portability. An
   independent test is proposed here for review, following the principle used
   by Urban MCP. The proof applies to the capabilities and environments
   exercised. Domain API bindings and applied cases have their own evidence.
