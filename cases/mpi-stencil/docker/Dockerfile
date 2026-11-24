ARG BASE_IMAGE=polisplexity-hpc/slurm-test:local
FROM ${BASE_IMAGE} AS mpi-dependencies

COPY cases/mpi-stencil/docker/install.sh /tmp/install-mpi.sh
RUN /bin/sh /tmp/install-mpi.sh && rm -f /tmp/install-mpi.sh

FROM mpi-dependencies AS mpi-case
COPY cases/mpi-stencil/heat.c cases/mpi-stencil/run.py ./cases/mpi-stencil/
COPY tools/check_mpi_stencil.py ./tools/
COPY cases/portable-python/docker/start.sh /usr/local/bin/polis-slurm-test
RUN mpicc -std=c11 -O3 -ffp-contract=off -Wall -Wextra -Werror \
    cases/mpi-stencil/heat.c -o cases/mpi-stencil/heat -lcrypto -lm
CMD ["/opt/polis-venv/bin/python", "-m", "tools.check_mpi_stencil"]
