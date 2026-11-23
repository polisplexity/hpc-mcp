# HPC MCP master test record

Edition: 2026-11-23.

| Scope | Status | Evidence boundary |
|---|---|---|
| CIMAT account and remote execution | Rechecked 2026-11-23 | SSH authenticated. Python 3, Docker and Open MPI were visible. Slurm and PBS client commands were absent in the checked login shell and usual binary paths on this node. Tests use the authorized SSH and Docker access. |
| OLDT worker and artifact contracts | Documented upstream | [OLDT Data Factory](https://github.com/polisplexity/open-local-digital-twin/blob/main/docs/DATA_FACTORY_REMOTE_SERVER_CONFIGURATION.md) documents portable dispatch and artifact flow. |
| Inventory metadata | Local verification | The registry and generated inventory can be checked with the included validator. |
| Fixed CIMAT CPU workload | Native passed | [Native receipt](cases/cimat-guanajuato/evidence/native-cpu-20261122.json) records local and remote byte parity and sum 333338333350000. |
| Fixed CIMAT CPU workload via MCP stdio | MCP passed | [MCP receipt](cases/cimat-guanajuato/evidence/mcp-cpu-20261122.json) records matching native/MCP outputs and an out-of-scope target rejection. The first harness attempt received a valid text result without structuredContent. The client now accepts a JSON text block, and the tool advertises a structured return. |
| Portable Python job via CLI and MCP stdio | Local and CIMAT SSH passed | [Portable job evidence](cases/portable-python/evidence/portable-20261123.json) records byte parity with a native comparator, exit 7, exit 0 with missing output, timeout, input rejection, and a separately supplied program. Both workers used Python 3.10.12. The successful SSH run used one CPU in its affinity, a 128 MiB address-space ceiling and a 10-second wall timeout. |
| Slurm submission and recovery in development | Passed | [Slurm laboratory evidence](cases/portable-python/evidence/slurm-lab-20261123.json) records native CLI, the pinned Silogen MCP provider, Polisplexity MCP, exit 7, a denied preflight, and recovery of exactly one allocation after losing the acknowledgment. An interrupted request with no evidence stayed unknown. |
| Slurm in Docker at CIMAT | Passed | [CIMAT Docker evidence](cases/portable-python/evidence/slurm-cimat-docker-20261123.json) records controller, worker and accounting tests with Slurm 26.05.5. Two simultaneous requests sharing a UUID produced a single allocation. A different UUID produced its own job, and a conflicting manifest was rejected. |
| Site-managed Slurm, applied cases, Codex and Hermes | Pending | Qualify a site-managed queue when a workload calls for it. See the [Slurm qualification issue](https://github.com/polisplexity/hpc-mcp/issues/3) and [RFC 0001](docs/rfc/0001-hpc-job-contract.md). |

Record each actual run with source revision, execution route, recipe and input
hashes, resource allocation, provider/worker job ID, timestamps, captured exit
status, checksums and review of outputs and claims. Keep failed and partial
attempts visible. State whether each resource measurement covers the job, a
shared device or the complete node.
