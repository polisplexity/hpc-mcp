#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
cd -- "$repo"
image=polisplexity-hpc/mpi-sweep:local
if (( $# > 0 )); then
    image=$1
    shift
fi
options=("$@")
revision=$(git rev-parse HEAD)
short_revision=$(git rev-parse --short=12 HEAD)
slurm="polisplexity-hpc/slurm-test:$short_revision"
heat="polisplexity-hpc/mpi-heat:$short_revision"
copper="polisplexity-hpc/mpi-copper:$short_revision"

build_layer() {
    local dockerfile=$1 base=$2 target=$3
    shift 3
    git archive "$revision" "$dockerfile" "$@" |
        docker build "${options[@]}" --platform linux/amd64 --file "$dockerfile" \
            --build-arg "BASE_IMAGE=$base" --label "org.opencontainers.image.revision=$revision" \
            --tag "$target" -
}

bash cases/portable-python/docker/build.sh "$slurm" "${options[@]}"
build_layer cases/mpi-stencil/docker/Dockerfile "$slurm" "$heat" \
    cases/mpi-stencil/docker/install.sh cases/mpi-stencil/heat.c cases/mpi-stencil/run.py \
    cases/portable-python/docker/start.sh tools/check_mpi_stencil.py
build_layer cases/mpi-copper/docker/Dockerfile "$heat" "$copper" \
    cases/mpi-stencil/docker/install.sh cases/mpi-copper/in.copper cases/mpi-copper/run.py \
    cases/mpi-copper/pin.py tools/check_mpi_copper.py
build_layer cases/mpi-copper/docker/Dockerfile.sweep "$copper" "$image" \
    hpc_mcp cases/mpi-copper/run.py cases/mpi-copper/in.copper tools/audit_copper_sweep.py
