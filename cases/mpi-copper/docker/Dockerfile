ARG BASE_IMAGE=polisplexity-hpc/mpi-heat:local
FROM ${BASE_IMAGE} AS lammps-dependencies

COPY cases/mpi-stencil/docker/install.sh /tmp/install-lammps.sh
RUN /bin/sh /tmp/install-lammps.sh lammps && rm -f /tmp/install-lammps.sh

FROM lammps-dependencies AS copper-case
COPY cases/mpi-copper/in.copper cases/mpi-copper/run.py cases/mpi-copper/pin.py ./cases/mpi-copper/
COPY tools/check_mpi_copper.py ./tools/
CMD ["/opt/polis-venv/bin/python", "-m", "tools.check_mpi_copper"]
