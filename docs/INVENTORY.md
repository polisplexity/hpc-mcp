# Polisplexity HPC MCP integration inventory

Edition 2026-11-24 · 43 entries.

Generated from [the source registry](../registry/tools.json).
The catalog includes deployment targets, connectors, dependencies,
reference tools and workloads. Each entry describes a proposed test.
See the [master record](../MASTER_TEST_RECORD.md) for observed results.

Decisions: pilot (first case), evaluate (near-term candidate), alternate
(substitute), dependency (used inside another tool), reference (human
or benchmark reference), research (later experiment).

## Contents

- [CIMAT Guanajuato](#cimat) — Institutional targets
- [OpenSSH](#openssh) — Institutional targets
- [OLDT Data Factory](#oldt-data-factory) — Workloads and acceptance
- [Local CPU reference runner](#local-worker) — Workloads and acceptance
- [Slurm CLI](#slurm-cli) — Schedulers
- [slurmrestd](#slurm-rest) — Schedulers
- [OpenPBS](#openpbs) — Schedulers
- [HTCondor](#htcondor) — Schedulers
- [IBM Spectrum LSF](#lsf) — Schedulers
- [Flux Framework](#flux) — Schedulers
- [CSC Slurm MCP](#csc-mcp) — Existing MCP and service APIs
- [Community HPC MCP](#community-hpc-mcp) — Existing MCP and service APIs
- [FirecREST](#firecrest) — Existing MCP and service APIs
- [Globus Compute](#globus-compute) — Existing MCP and service APIs
- [Open OnDemand](#open-ondemand) — Existing MCP and service APIs
- [SFTP](#sftp) — Data movement
- [rsync](#rsync) — Data movement
- [Globus Transfer](#globus-transfer) — Data movement
- [S3-compatible object storage](#s3-artifacts) — Data movement
- [Docker Engine](#docker) — Execution environments
- [Apptainer](#apptainer) — Execution environments
- [Environment Modules](#environment-modules) — Execution environments
- [Spack](#spack) — Execution environments
- [Open MPI](#openmpi) — Execution environments
- [LAMMPS](#lammps) — Scientific workflows
- [Nextflow](#nextflow) — Scientific workflows
- [Snakemake](#snakemake) — Scientific workflows
- [Parsl](#parsl) — Scientific workflows
- [Dask Jobqueue](#dask-jobqueue) — Scientific workflows
- [Ray Jobs](#ray-jobs) — Scientific workflows
- [Kubernetes Jobs + Kueue](#kueue) — Cloud and institutional batch
- [AWS Batch](#aws-batch) — Cloud and institutional batch
- [Azure Batch](#azure-batch) — Cloud and institutional batch
- [Google Cloud Batch](#google-batch) — Cloud and institutional batch
- [Slurm accounting and efficiency](#slurm-accounting) — Observability
- [NVIDIA DCGM Exporter](#dcgm) — Observability
- [Urban MCP SWMM](#urban-swmm) — Workloads and acceptance
- [Urban MCP SUMO](#urban-sumo) — Workloads and acceptance
- [CUDA-Q distributed simulation](#cuda-q-hpc) — Workloads and acceptance
- [Lmod](#lmod) — Execution environments
- [OpenMP](#openmp) — Execution environments
- [DMTCP](#dmtcp) — Recovery
- [IBM LSF quantum plugins](#ibm-lsf-quantum) — Workloads and acceptance

<a id="cimat"></a>
## CIMAT Guanajuato

**Family** — Institutional targets. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — Authorized institutional account; public Slurm manual
- **Reuse** — Use the account's available submission mechanism, and the site's allocation, storage and identity rules.
- **Build** — Add a local connection profile with capability discovery. Choose the bounded SSH worker or the supported queue after checking the assigned host. Keep credentials and site-specific paths outside this repository.
- **Acceptance test** — Check account capabilities and scratch read/write with synthetic data. Run a fixed CPU fixture natively and through MCP, then transfer a public Guanajuato tile package and verify the output in OLDT. Record the available queue and actual consumption.
- **Sources** — [Upstream source 1](https://hpc.cimat.mx/Manuales_hpc), [Upstream source 2](https://hpc.cimat.mx/Infraestructura_HPC)

<a id="openssh"></a>
## OpenSSH

**Family** — Institutional targets. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — SSH client with approved host identity handling
- **Reuse** — Use the system SSH client and existing authorized authentication and host-key policy.
- **Build** — Implement a constrained worker profile for sites that permit direct execution. Pass typed recipe arguments, constrain working paths and persist the handoff before dispatch.
- **Acceptance test** — Exercise a known host, host-key mismatch, permission denial and disconnect after dispatch. Reconcile the existing work without submitting it twice.
- **Sources** — [Upstream source 1](https://www.openssh.com/manual.html)

<a id="oldt-data-factory"></a>
## OLDT Data Factory

**Family** — Workloads and acceptance. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — External-worker dispatch, HPC package generator and result import
- **Reuse** — Reuse dispatch manifests, viewer-artifacts stage, portable inputs and existing result and artifact contracts.
- **Build** — Bind the worker and MCP job IDs to the OLDT dispatch and revision. Return artifacts for explicit import and validation.
- **Acceptance test** — Run the same permitted Guanajuato package locally and remotely. Check manifest, CRS, coverage, feature IDs, MVT/PMTiles/3D Tiles validity and successful opening in a test Twin.
- **Sources** — [Upstream source 1](https://raw.githubusercontent.com/polisplexity/open-local-digital-twin/main/docs/DATA_FACTORY_REMOTE_SERVER_CONFIGURATION.md)

<a id="local-worker"></a>
## Local CPU reference runner

**Family** — Workloads and acceptance. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — Reviewed fixed local recipe and OS process lifecycle
- **Reuse** — Reuse the same versioned program and input bundle used in the remote job.
- **Build** — Create a tiny native reference and shared expected output. Preserve resource limits and a stable exit status in its lifecycle receipt.
- **Acceptance test** — Verify exact synthetic results, nonzero exit handling and timeout. Compare with the first remote and MCP results.
- **Sources** — [Upstream source 1](https://github.com/polisplexity/open-local-digital-twin)

<a id="slurm-cli"></a>
## Slurm CLI

**Family** — Schedulers. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — sbatch, squeue, sacct, scancel and site QoS
- **Reuse** — Reuse native scheduler, resource requests, accounting and cancellation semantics.
- **Build** — Map typed resource requests and native states, including arrays and jobs no longer visible in the queue. Reconcile unknown submission outcomes.
- **Acceptance test** — Submit a small job and array using an authorized account. Check pending, success, failure, cancellation, accounting retention and native versus MCP output.
- **Sources** — [Upstream source 1](https://slurm.schedmd.com/quickstart.html), [Upstream source 2](https://slurm.schedmd.com/job_array.html)

<a id="slurm-rest"></a>
## slurmrestd

**Family** — Schedulers. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Versioned OpenAPI via a site-enabled Slurm REST service
- **Reuse** — Reuse the site's authenticated REST entry point and advertised API version.
- **Build** — Add conformance against the common job fields, preserving provider errors and version differences.
- **Acceptance test** — Compare submit, query and cancel with the CLI on the same test cluster. Verify unavailable service, authorization refusal and unsupported schema.
- **Sources** — [Upstream source 1](https://slurm.schedmd.com/rest.html)

<a id="openpbs"></a>
## OpenPBS

**Family** — Schedulers. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — qsub, qstat and qdel
- **Reuse** — Reuse PBS job scripts, resource syntax, arrays and lifecycle commands.
- **Build** — Translate the typed job request into the existing OLDT PBS bundle and normalize state only where meanings match.
- **Acceptance test** — Run a two-task job, retain per-task results, test rejection and cancellation, and compare PBS output with direct execution.
- **Sources** — [Upstream source 1](https://github.com/openpbs/openpbs), [Upstream source 2](https://raw.githubusercontent.com/openpbs/openpbs/master/doc/man1/qsub.1B)

<a id="htcondor"></a>
## HTCondor

**Family** — Schedulers. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Python bindings and submit descriptions
- **Reuse** — Reuse Schedd queries, native submit API and file-transfer features.
- **Build** — Map independent scenario tasks and preserve the cluster and process identity for each output.
- **Acceptance test** — Run an independently verifiable batch, force one job into a held state and compare job history and outputs with the native path.
- **Sources** — [Upstream source 1](https://htcondor.readthedocs.io/en/main/apis/python-bindings/tutorials/Submitting-and-Managing-Jobs.html)

<a id="lsf"></a>
## IBM Spectrum LSF

**Family** — Schedulers. **Decision** — research. **Status** — candidate.

- **Upstream interface** — bsub, bjobs and bkill at an approved installation
- **Reuse** — Reuse the native queue and resource request syntax.
- **Build** — Add a profile only for a confirmed site and inspect its licensed client and parsing interface.
- **Acceptance test** — Check successful and rejected jobs and compare owner-scoped cancellation and accounting with direct LSF operation.
- **Sources** — [Upstream source 1](https://www.ibm.com/products/spectrum-lsf), [Upstream source 2](https://github.com/IBMSpectrumComputing/lsf-integrations)

<a id="flux"></a>
## Flux Framework

**Family** — Schedulers. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Flux job CLI and Python API
- **Reuse** — Reuse Flux resource and job abstractions at sites with a supported deployment.
- **Build** — Map one allocation-scoped workload and keep nested job IDs and parent allocation visible.
- **Acceptance test** — Run a job in a non-production Flux allocation and verify resources, completion and cancellation against the native receipt.
- **Sources** — [Upstream source 1](https://flux-framework.readthedocs.io/en/latest/)

<a id="csc-mcp"></a>
## CSC Slurm MCP

**Family** — Existing MCP and service APIs. **Decision** — evaluate. **Status** — candidate.

- **Upstream interface** — Site-provided MCP for Slurm
- **Reuse** — Inspect the actual tool contract and reuse bounded scheduler tools if the site offers a supported path.
- **Build** — Add a profile and result-bundle translation only for required operations absent from the current tool contract.
- **Acceptance test** — List tools, run a permitted fixture using native and MCP paths, compare results and test a disallowed operation in the authorized profile.
- **Sources** — [Upstream source 1](https://docs.csc.fi/supercomputing/ai-tools/agent-env/)

<a id="community-hpc-mcp"></a>
## Community HPC MCP

**Family** — Existing MCP and service APIs. **Decision** — evaluate. **Status** — candidate.

- **Upstream interface** — Per-user Slurm and PBS MCP project
- **Reuse** — Review the current license, tool list, scheduler-only configuration and versions.
- **Build** — Use only the operations required by the project and keep shell and general file editing outside the integration profile.
- **Acceptance test** — In an isolated lab review all exposed tools, then compare a fixed job with the native scheduler and verify the configured scope.
- **Sources** — [Upstream source 1](https://github.com/mfukudaQED/hpc-mcp)

<a id="firecrest"></a>
## FirecREST

**Family** — Existing MCP and service APIs. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — CSCS REST and client endpoints for jobs and transfer
- **Reuse** — Use the site-provided authorization, scheduler and staged transfer APIs.
- **Build** — Preserve remote job and transfer IDs in a shared receipt and map site-specific availability into discovery.
- **Acceptance test** — Run a fixture with approved test data, compare the returned job record, verify checksums and handle token expiration and transfer failure.
- **Sources** — [Upstream source 1](https://docs.cscs.ch/access/firecrest/)

<a id="globus-compute"></a>
## Globus Compute

**Family** — Existing MCP and service APIs. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Compute endpoint and service API
- **Reuse** — Use the institution's provisioned endpoint and task lifecycle where accepted.
- **Build** — Register fixed compute functions or reviewed recipes through the existing endpoint and reconcile their task IDs.
- **Acceptance test** — Submit an approved deterministic CPU fixture and exercise lost client connection, duplicate handling and expired credentials.
- **Sources** — [Upstream source 1](https://compute.api.globus.org/redoc)

<a id="open-ondemand"></a>
## Open OnDemand

**Family** — Existing MCP and service APIs. **Decision** — reference. **Status** — candidate.

- **Upstream interface** — Institutional web portal and job tooling
- **Reuse** — Use the site portal as a human reference for available queues and job states.
- **Build** — Record the supported automation route offered by the site. Treat UI functions as operator references when a stable API is unavailable.
- **Acceptance test** — Compare a test job view and accounting fields against the scheduler path with the same authorized account.
- **Sources** — [Upstream source 1](https://osc.github.io/ood-documentation/latest/)

<a id="sftp"></a>
## SFTP

**Family** — Data movement. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — OpenSSH file transfer
- **Reuse** — Reuse authorized SFTP with separate input and output paths.
- **Build** — Add a manifest for file IDs, bytes and hashes, transfer to a temporary name and publish a completed artifact only after verification.
- **Acceptance test** — Interrupt a transfer, resume or retry via the supported mechanism, and reject a changed hash or out-of-scope target path.
- **Sources** — [Upstream source 1](https://man.openbsd.org/sftp.1)

<a id="rsync"></a>
## rsync

**Family** — Data movement. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — SSH-backed incremental file synchronization
- **Reuse** — Reuse the existing Data Factory transfer plans and native rsync features.
- **Build** — Execute against configured source and destination roots and return a checked transfer receipt.
- **Acceptance test** — Run initial and restart transfers on a test bundle, attempt an out-of-scope symlink, then verify exact output hashes.
- **Sources** — [Upstream source 1](https://rsync.samba.org/documentation.html), [Upstream source 2](https://raw.githubusercontent.com/polisplexity/open-local-digital-twin/main/docs/DATA_FACTORY_REMOTE_SERVER_CONFIGURATION.md)

<a id="globus-transfer"></a>
## Globus Transfer

**Family** — Data movement. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Managed transfers between configured collections
- **Reuse** — Use the existing task and monitoring API and supported checksum mode.
- **Build** — Bind the two collection identities, transfer task and artifact checksums to the job receipt.
- **Acceptance test** — Transfer a permitted test bundle, compare hashes, and exercise cancellation, authorization failure and retry.
- **Sources** — [Upstream source 1](https://docs.globus.org/api/transfer/)

<a id="s3-artifacts"></a>
## S3-compatible object storage

**Family** — Data movement. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Provider SDK and explicit artifact URIs
- **Reuse** — Reuse a configured bucket, object versions and supported checksum metadata.
- **Build** — Keep per-job prefixes and preserve exact version, size, content SHA-256 and expiry in the import manifest.
- **Acceptance test** — Test upload, interrupted retrieval, object replacement and checksum rejection without relying on multipart ETags as content hashes.
- **Sources** — [Upstream source 1](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html)

<a id="docker"></a>
## Docker Engine

**Family** — Execution environments. **Decision** — pilot. **Status** — candidate.

- **Upstream interface** — Images and controlled runtime configuration
- **Reuse** — Reuse the permitted site runtime, with fixed images addressed by digest.
- **Build** — Pin the command, mounts, CPU and memory settings at the worker boundary and separate logs from results.
- **Acceptance test** — Run the same image twice, verify results and limits, and confirm that a disallowed mount or resource request is rejected upstream of submission.
- **Sources** — [Upstream source 1](https://docs.docker.com/engine/containers/resource_constraints/)

<a id="apptainer"></a>
## Apptainer

**Family** — Execution environments. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — SIF containers and site MPI integration
- **Reuse** — Use the center-supported container execution and bind-mount policy.
- **Build** — Add a compatible SIF build or approved digest reference and map launcher and MPI compatibility.
- **Acceptance test** — Repeat a CPU fixture and two-rank MPI fixture under the authorized scheduler, checking image identity and portability.
- **Sources** — [Upstream source 1](https://apptainer.org/docs/user/latest/mpi.html)

<a id="environment-modules"></a>
## Environment Modules

**Family** — Execution environments. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Site-defined modulefiles and versions
- **Reuse** — Reuse the module stack provided at the institution.
- **Build** — Record loaded modules and compiler/runtime versions in the job manifest.
- **Acceptance test** — Rebuild a fixture in a clean job environment and show an unavailable module gives a clear failure rather than a fallback.
- **Sources** — [Upstream source 1](https://modules.readthedocs.io/en/latest/)

<a id="spack"></a>
## Spack

**Family** — Execution environments. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Locked scientific software environments
- **Reuse** — Use a site-approved Spack environment, compiler and external dependency definitions.
- **Build** — Store a recipe reference and lock-file digest, with compatibility rules for the chosen node.
- **Acceptance test** — Build the same fixture from a fresh environment and compare runtime dependencies and outputs across two authorized targets.
- **Sources** — [Upstream source 1](https://spack.readthedocs.io/en/latest/environments.html)

<a id="openmpi"></a>
## Open MPI

**Family** — Execution environments. **Decision** — evaluate. **Status** — mcp-verified.

- **Upstream interface** — MPI runtime and launcher
- **Reuse** — Reuse Open MPI for process launch and communication within a Slurm allocation.
- **Build** — Record ranks, allocated CPUs, rank affinity, transport and image versions. Leave scientific parallelization to the workload.
- **Acceptance test** — Compare one, two and four ranks for a fixed periodic heat stencil on one node. Require identical field digests and agreement with the analytic solution, and record speedup separately for the kernel and launcher.
- **Sources** — [Upstream source 1](https://docs.open-mpi.org/en/main/)

<a id="lammps"></a>
## LAMMPS

**Family** — Scientific workflows. **Decision** — evaluate. **Status** — mcp-verified.

- **Upstream interface** — Molecular dynamics executable and documented input format
- **Reuse** — Run the packaged MPI executable and use its distributed force calculations and thermodynamic output.
- **Build** — Stage the simulation inputs with hashes and recover thermodynamic samples through the existing Slurm job contract.
- **Acceptance test** — Run fixed-volume copper dynamics with one, two and four ranks. Require matching thermodynamic curves within tolerance, atom conservation and bounded energy deviation.
- **Sources** — [Upstream source 1](https://docs.lammps.org/stable/pair_eam.html), [Upstream source 2](https://doi.org/10.1103/PhysRevB.33.7983)

<a id="nextflow"></a>
## Nextflow

**Family** — Scientific workflows. **Decision** — evaluate. **Status** — candidate.

- **Upstream interface** — Native workflow executors and run metadata
- **Reuse** — Use versioned Nextflow pipelines and existing scheduler executors.
- **Build** — Map pipeline parameters and final artifacts without reimplementing its DAG or task retry engine.
- **Acceptance test** — Run a three-step synthetic workflow locally and on a test queue. Force one step to fail and verify restart and artifact identity.
- **Sources** — [Upstream source 1](https://docs.seqera.io/nextflow/executor)

<a id="snakemake"></a>
## Snakemake

**Family** — Scientific workflows. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Rules, workflow execution and Slurm executor plugin
- **Reuse** — Reuse the original rules and supported executor plugin.
- **Build** — Bind input assets, selected targets and output manifest to the MCP job request.
- **Acceptance test** — Compare local and Slurm output hashes for a three-rule workflow, check missing input and resumption.
- **Sources** — [Upstream source 1](https://snakemake.github.io/snakemake-plugin-catalog/plugins/executor/slurm.html)

<a id="parsl"></a>
## Parsl

**Family** — Scientific workflows. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Python workflow and execution providers
- **Reuse** — Reuse the application's Python DAG and supported execution provider.
- **Build** — Register versioned workflows and capture outputs and statuses at the recipe boundary.
- **Acceptance test** — Run an independent-task workload, fail one task and verify final artifacts and failure scope with a direct Parsl run.
- **Sources** — [Upstream source 1](https://parsl.readthedocs.io/en/stable/)

<a id="dask-jobqueue"></a>
## Dask Jobqueue

**Family** — Scientific workflows. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Native Dask cluster launchers for batch systems
- **Reuse** — Reuse the application's Dask tasks and existing cluster factory.
- **Build** — Add a scoped resource request for the scheduler and record worker counts, failure and cleanup.
- **Acceptance test** — Compare a partitioned spatial summary to a serial reference and test a worker failure without losing the final job state.
- **Sources** — [Upstream source 1](https://jobqueue.dask.org/en/stable/)

<a id="ray-jobs"></a>
## Ray Jobs

**Family** — Scientific workflows. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Jobs API on a configured Ray deployment
- **Reuse** — Reuse JobSubmissionClient and existing workload definitions.
- **Build** — Bind Ray submission and logs to the common receipt and record which cluster provisioned the resources.
- **Acceptance test** — Run a small parallel fixture, recover the receipt after client exit and confirm cancellation only affects the owned job.
- **Sources** — [Upstream source 1](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/index.html)

<a id="kueue"></a>
## Kubernetes Jobs + Kueue

**Family** — Cloud and institutional batch. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Kubernetes Job API and Kueue admission and quotas
- **Reuse** — Reuse Job and queue policies in an approved namespace.
- **Build** — Map recipes to approved Job templates and keep the workload admission state distinct from execution.
- **Acceptance test** — Check one admitted job, one job pending quota and one failed pod. Verify output access is scoped to the job namespace.
- **Sources** — [Upstream source 1](https://kubernetes.io/docs/concepts/workloads/controllers/job/), [Upstream source 2](https://kueue.sigs.k8s.io/docs/overview/)

<a id="aws-batch"></a>
## AWS Batch

**Family** — Cloud and institutional batch. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Batch job definitions, queues, arrays and multi-node jobs
- **Reuse** — Reuse official batch APIs and the selected job definition.
- **Build** — Add identity for queue and job definition versions, permitted project and cost/capacity fields where available.
- **Acceptance test** — Run a bounded CPU job and array in an authorized environment. Capture native IDs, failure reason, artifacts and observable billing units.
- **Sources** — [Upstream source 1](https://docs.aws.amazon.com/batch/latest/userguide/jobs.html)

<a id="azure-batch"></a>
## Azure Batch

**Family** — Cloud and institutional batch. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Batch pools, jobs and tasks
- **Reuse** — Reuse official Batch client and an approved pool.
- **Build** — Map tasks and their children to per-job outputs and preserve pool sizing and start latency.
- **Acceptance test** — Run a fixed task on an authorized pool, verify outputs and compare lifecycle after a failing task and client reconnection.
- **Sources** — [Upstream source 1](https://learn.microsoft.com/en-us/azure/batch/batch-technical-overview)

<a id="google-batch"></a>
## Google Cloud Batch

**Family** — Cloud and institutional batch. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Jobs API, tasks and configured compute resources
- **Reuse** — Reuse the existing Batch service and permitted storage identities.
- **Build** — Map the native job and task groups into the project receipt and preserve region and resource profile.
- **Acceptance test** — Run a bounded fixture with a fixed image, verify the output hash, handle quota rejection and reconcile the same job ID after reconnect.
- **Sources** — [Upstream source 1](https://cloud.google.com/batch/docs/get-started)

<a id="slurm-accounting"></a>
## Slurm accounting and efficiency

**Family** — Observability. **Decision** — evaluate. **Status** — candidate.

- **Upstream interface** — sacct and available site accounting data
- **Reuse** — Use native elapsed, CPU and memory fields where available.
- **Build** — Record units, observation scope and unavailable fields, keeping allocated resources distinct from consumption.
- **Acceptance test** — Compare MCP metrics with native accounting for a short CPU job and check the missing-accounting case.
- **Sources** — [Upstream source 1](https://slurm.schedmd.com/sacct.html)

<a id="dcgm"></a>
## NVIDIA DCGM Exporter

**Family** — Observability. **Decision** — research. **Status** — candidate.

- **Upstream interface** — DCGM metrics exposed to Prometheus
- **Reuse** — Reuse site-approved GPU telemetry with access to authorized labels.
- **Build** — Bind available samples to the job allocation, and represent shared-device and missing attribution accurately.
- **Acceptance test** — Run a fixed GPU job where permitted, compare receipt times with telemetry, and record missing or shared metrics explicitly.
- **Sources** — [Upstream source 1](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)

<a id="urban-swmm"></a>
## Urban MCP SWMM

**Family** — Workloads and acceptance. **Decision** — evaluate. **Status** — candidate.

- **Upstream interface** — Existing EPA SWMM and PySWMM case and observed rainfall fixtures
- **Reuse** — Reuse the historical case, engine, inputs and permitted recipes.
- **Build** — Make a typed parameter-sweep workload, preserving model baseline and one output per scenario.
- **Acceptance test** — Compare all per-node rows against native independent runs within declared tolerances, test one failed task and measure batch overhead.
- **Sources** — [Upstream source 1](https://github.com/polisplexity/urban-mcp/tree/main/cases/two-city-swmm)

<a id="urban-sumo"></a>
## Urban MCP SUMO

**Family** — Workloads and acceptance. **Decision** — evaluate. **Status** — candidate.

- **Upstream interface** — Existing SUMO experiment, model and fixed seeds
- **Reuse** — Reuse native models and outputs, including interrupted and incomplete trips.
- **Build** — Schedule independent repetitions and aggregate them without changing per-trip meaning.
- **Acceptance test** — Compare fixed-seed outputs with native single runs and preserve all trip, teleport and censor accounting when aggregating.
- **Sources** — [Upstream source 1](https://github.com/polisplexity/urban-mcp/tree/main/cases/two-city-sumo)

<a id="cuda-q-hpc"></a>
## CUDA-Q distributed simulation

**Family** — Workloads and acceptance. **Decision** — research. **Status** — candidate.

- **Upstream interface** — CUDA-Q distributed backends and MPI
- **Reuse** — Use the simulation runtime and CUDA-aware infrastructure, with the Quantum circuit manifest as input.
- **Build** — Bind circuit identity and simulator configuration to an HPC recipe and return measurements to Quantum.
- **Acceptance test** — Check a known circuit locally and across the authorized MPI allocation. Compare probabilities within tolerance and report simulator configuration.
- **Sources** — [Upstream source 1](https://nvidia.github.io/cuda-quantum/latest/using/backends/simulators.html)

<a id="lmod"></a>
## Lmod

**Family** — Execution environments. **Decision** — alternate. **Status** — candidate.

- **Upstream interface** — Lua modulefiles and site environment hierarchy
- **Reuse** — Reuse the active module hierarchy on the authorized cluster.
- **Build** — Record exact modules and resolve environment dependencies through the site's normal startup path.
- **Acceptance test** — Compare interactive discovery with a clean batch run, verify the same modules are loaded and report a missing dependency explicitly.
- **Sources** — [Upstream source 1](https://lmod.readthedocs.io/en/stable/index.html)

<a id="openmp"></a>
## OpenMP

**Family** — Execution environments. **Decision** — dependency. **Status** — candidate.

- **Upstream interface** — Threads and affinity settings in a compatible compiled workload
- **Reuse** — Use the existing workload's OpenMP parallel regions.
- **Build** — Bind the requested CPUs to explicit thread settings and record the observed environment.
- **Acceptance test** — Compare a serial and threaded reference reduction, verify thread allocation and measure overhead without assuming speedup.
- **Sources** — [Upstream source 1](https://www.openmp.org/specifications/)

<a id="dmtcp"></a>
## DMTCP

**Family** — Recovery. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Checkpoint and restart for compatible Linux processes
- **Reuse** — Reuse the workload's own checkpoint when available and evaluate DMTCP for a supported process.
- **Build** — Associate checkpoint version, hash and compatible target scope with an explicit resume operation.
- **Acceptance test** — Interrupt a permitted job, restore from its checkpoint and verify final results and restricted checkpoint access.
- **Sources** — [Upstream source 1](https://dmtcp.github.io/quick-start.html)

<a id="ibm-lsf-quantum"></a>
## IBM LSF quantum plugins

**Family** — Workloads and acceptance. **Decision** — research. **Status** — candidate.

- **Upstream interface** — Vendor-backed integration of LSF workload management and QPU dispatch
- **Reuse** — Inspect existing plugin code, dependencies and target support at a site already authorized to use LSF and a quantum backend.
- **Build** — Map the scheduler job and quantum execution IDs into linked receipts if the original tools expose both. Reuse the existing scheduler and provider queue.
- **Acceptance test** — Run one fixed simulator-backed job first. In an authorized QPU experiment verify independent scheduler and device states, result provenance and the scope of cancellation.
- **Sources** — [Upstream source 1](https://github.com/IBM/lsf-quantum)
