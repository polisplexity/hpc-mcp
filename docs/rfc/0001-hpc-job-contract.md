# RFC 0001 · Portable scientific jobs

Proposed · 2026-11-22.

## Product boundary

A job selects a versioned recipe and an authorized execution profile. The
profile describes the submission path, supported resources and output storage.
CIMAT is the first candidate profile. The design allows SSH-worker execution
where the site permits it and scheduler submission where the account provides it.

## Proposed operations

- Discover authorized profiles and their observed capacities.
- Prepare a job from a known recipe, manifest and requested resources.
- Submit a prepared job and retain both project and backend IDs.
- Read state and scoped logs, reconcile ambiguous submission, cancel owned work.
- Retrieve a verified result manifest and artifact references.

Keep native state, exit reason and array task IDs. Use an idempotency key
bound to the submitted recipe, inputs and parameters. Persist the dispatch
intent and reconcile uncertainty with backend evidence before retrying.
Record whether queue time and resource accounting are available. Keep
authentication, authorized storage and site-specific defaults in the local
profile. Production jobs should be described with typed arguments to
reviewed recipes.

## Initial work

1. Fix the native synthetic fixture, receipt and failed-input cases.
2. Confirm the available CIMAT route and prove native execution.
3. Reuse an existing MCP profile if it covers the route. Add only the missing
   lifecycle, result and OLDT binding operations.
4. Admit a public, bounded Guanajuato package and compare local and remote
   viewer artifacts. Run the same task independently in Codex and Hermes.
5. Evaluate portable Slurm/PBS profiles and one Urban MCP parameter sweep as
   separate milestones with their own evidence.
