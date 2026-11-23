#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
case_path=cases/portable-python
docker_path="$case_path/docker"
image=polisplexity-hpc/slurm-test:local
if (( $# > 0 )); then
    image=$1
    shift
fi
revision=$(git -C "$repo" rev-parse HEAD)

git -C "$repo" archive "$revision" LICENSE hpc_mcp schemas \
    tools/check_portable_job.py tools/check_slurm_job.py \
    cases/cimat-guanajuato/requirements-mcp.txt \
    "$case_path/job.json" "$case_path/parameters.json" "$case_path/program.py" "$case_path/client-example" \
    "$docker_path/Dockerfile" "$docker_path/install.sh" \
    "$docker_path/python-constraints.txt" "$docker_path/start.sh" |
    docker build "$@" --platform linux/amd64 --file "$docker_path/Dockerfile" \
        --label "org.opencontainers.image.revision=$revision" --tag "$image" -
