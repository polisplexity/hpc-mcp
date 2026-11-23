# HPC MCP master test record

Edition: 2026-11-22.

| Scope | Status | Evidence boundary |
|---|---|---|
| CIMAT account and remote execution | Rechecked 2026-11-22 | SSH authenticated. Python 3, Docker and Open MPI were visible. Slurm, PBS, Apptainer and NVIDIA CLI commands were absent from the account's current PATH. Visible logical CPUs are not an allocation. CIMAT's [public documentation](https://hpc.cimat.mx/Manuales_hpc) describes institutional Slurm. |
| OLDT worker and artifact contracts | Documented upstream | [OLDT Data Factory](https://github.com/polisplexity/open-local-digital-twin/blob/main/docs/DATA_FACTORY_REMOTE_SERVER_CONFIGURATION.md) documents portable dispatch and artifact flow. |
| Inventory metadata | Local verification | The registry and generated inventory can be checked with the included validator. |
| Fixed CIMAT CPU workload | Native passed | [Native receipt](cases/cimat-guanajuato/evidence/native-cpu-20261122.json) records local and remote byte parity and sum 333338333350000. |
| Fixed CIMAT CPU workload via MCP stdio | MCP passed | [MCP receipt](cases/cimat-guanajuato/evidence/mcp-cpu-20261122.json) records matching native/MCP outputs and an out-of-scope target rejection. The first harness attempt received a valid text result without structuredContent. The client now accepts a JSON text block, and the tool advertises a structured return. |
| Durable submission, city artifacts, Codex and Hermes | Pending | See the [first case](cases/cimat-guanajuato/README.md). |

Record each actual run with source revision, execution route, recipe and input
hashes, resource allocation, provider/worker job ID, timestamps, captured exit
status, checksums and review of outputs and claims. Keep failed and partial
attempts visible. State whether each resource measurement covers the job, a
shared device or the complete node.
