# Run an R job with a node-resident dataset

The managed R profile can stage a dataset that is already on the SSH
target. The operator enables the profile with a private remote directory in
`POLISPLEXITY_HPC_SSH_DATA_ROOT`. A trusted manifest pins a dataset path below
`datasets/` with its exact size and SHA-256. The worker checks both while
copying the file into the job's temporary directory on the same node.

Add `source` and `size_bytes` to the declared input. The manifest's `path`
still names the file the R script receives. Under this pilot the worker
supports up to 32 MiB per referenced input. Inline files and declared
outputs retain their 256 KiB limit. The R entrypoint stays inline and hashed.

With `"output_mode": "reference"`, HPC MCP saves declared outputs from a
successful R process in the private `objects/` directory. Each receipt
returns the artifact's `reference`, `sha256` and `size_bytes`.
`hpc_verify_artifact` reopens and hashes the stored object on the configured
SSH target. The reference remains valid across MCP sessions while that
storage profile retains the object.

## Repeat the acceptance case

Use the R case's [SSH and Hermes setup](README.md#reproduce-with-hermes).
Keep the authorized SSH alias and environment directory configured from that
setup. Create a private data directory on the same account. The seed command
generates the synthetic CSV on the node before Hermes starts.

```sh
POLISPLEXITY_HPC_SSH_DATA_ROOT=$(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
  "$POLISPLEXITY_HPC_SSH_PROFILE" 'umask 077; mktemp -d "$HOME/.hpc-mcp-data.XXXXXXXX"')
export POLISPLEXITY_HPC_SSH_DATA_ROOT
python -m tools.run_hermes_r_storage --seed-dataset
python -m tools.run_hermes_r_storage --output runs/ssh-r-storage
python -m tools.run_hermes_r_storage --verify-only --output runs/ssh-r-storage
```

## CIMAT acceptance on November 24, 2026

The pilot generated the 819,230-byte input directly on CIMAT before the
agent run. Hermes reused the cached Rocker R 4.5.2 image and executed the same
`summarize.R` from the earlier R case. The R job processed 65,536 rows.
Its 230-byte `summary.json` reported 411,156,480 total cents. Hermes read the
reference from the job receipt and verified it through HPC MCP.

An independent SSH audit read the input and the saved object on the node,
recomputed the result, and matched the input and output hashes. It also
confirmed the dataset's modification time preceded the R job. A separate
MCP session verified the same stored reference. The public trace redacts the
account's transient free disk figure.
[Hermes MCP trace](evidence/cimat-storage-20261124/mcp.jsonl) · [Verified record and node audit](evidence/cimat-storage-20261124/record.json)

Separate MCP checks rejected a wrong input byte count, a wrong input digest
and path traversal before the R script launched. A local storage check
rejected a symlink input and a tampered object.
