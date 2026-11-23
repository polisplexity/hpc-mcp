# CIMAT / Guanajuato HPC pilot

Pilot acceptance plan and first results · 2026-11-22.

## Question

Can an MCP client send a versioned city workload to an assigned compute
environment and return a result that OLDT can inspect? Use a verified CPU
fixture to exercise the connector first. Then use OLDT's viewer-artifacts
stage on a bounded public Guanajuato input.

## Reuse and implementation delta

- [CIMAT](https://hpc.cimat.mx/Manuales_hpc) supplies the authorized compute
  environment, usage limits and, where available to the account, a supported
  scheduler. Verify available commands, CPU/memory limits, permitted storage
  and runtime first. A documented institutional scheduler can differ from
  the worker assigned to the account.
- [OLDT Data Factory](https://github.com/polisplexity/open-local-digital-twin/blob/main/docs/DATA_FACTORY_REMOTE_SERVER_CONFIGURATION.md)
  supplies versioned dispatch, city-input packaging, the viewer-artifacts
  runner and output manifests.
- HPC MCP supplies one scoped submission profile, request validation and job
  reconciliation, log references and a verified output handoff. Use the
  installed queue if authorized, or a bounded recipe worker over SSH when
  the center permits direct execution.

## Stages and acceptance

| Stage | Planned test | Pass evidence |
|---|---|---|
| 1. Account and capabilities | Confirm the expected host identity and available scheduler or worker, input and output paths, runtime and authorized resource ceilings. | Scrubbed capability receipt and selected profile. |
| 2. Native CPU fixture | Run an independently checkable integer sum locally, then run the same version with the same inputs natively at the site. | Exact total, exit status and checksum; a failure and a timeout produce distinct receipts. |
| 3. MCP fixture | Execute the fixed fixture via its actual MCP entry point. Exercise status, logs, results, permission denial, wrong input hash and loss of client connection after submit. | Identical expected total; one native job for one idempotency key; recovery finds the same job; no out-of-scope output is readable. |
| 4. City data | Freeze a bounded public Guanajuato input, licenses and attribution, CRS, extent and expected MVT/PMTiles/3D Tiles counts. Run the same Data Factory recipe locally and remotely. | Checked manifest and artifact sizes/hashes; local and remote agree on geometry, feature identities and coverage under stated tolerances. Allow documented differences in serialization or timestamps. |
| 5. OLDT and two agent hosts | Import the reviewed output into a test Twin and open it. Give Codex and Hermes the same task in separate starting workspaces. | Verified map result and source identity; each host's trace, numeric/artifact comparison and final claims reviewed independently. |
| 6. Scaling follow-on | Execute a declared CPU sweep of independent SWMM scenarios with the admitted model, input rights and a documented concurrency limit. | Per-node parity with individual runs; total time, queue and transfer where available, failure reporting and evidence of when remote execution helps. |

## Run the fixed CPU probe

Python 3.10 or later. For CIMAT use an existing authorized SSH alias and
known host key. Run from a shell that already provides that SSH profile.

```sh
python -m pip install -r cases/cimat-guanajuato/requirements-mcp.txt
python cases/cimat-guanajuato/run_cpu_pilot.py
python cases/cimat-guanajuato/check_fixture_mcp.py
# Add --ssh-profile <your-approved-alias> to each command for CIMAT.
```

Local and CIMAT results matched byte for byte both in the
[native run](evidence/native-cpu-20261122.json) and through the
[stdio MCP tool](evidence/mcp-cpu-20261122.json). The sum of squares from
1 to 100,000 was 333338333350000. This is an interactive, read-only fixture
with a fixed workload and timeout. The elapsed time includes process and
SSH overhead. The scratch storage acceptance, queued jobs, Guanajuato
artifacts, failure recovery and agent observations remain open.

Record CPU allocation and measured use separately. Report execution, queue
and transfer times separately where observable. Keep credentials, machine
addresses and storage paths out of public evidence.
