FROM docker.io/library/debian@sha256:27b88700aef98dd3dd0b32538f8e5d662a88237ec8fbf969254c8d3c93dfdab1

LABEL org.opencontainers.image.title="Polisplexity HPC MCP Slurm test"
WORKDIR /opt/polisplexity/hpc-mcp
COPY cases/portable-python/docker/install.sh cases/portable-python/docker/python-constraints.txt /tmp/
COPY cases/cimat-guanajuato/requirements-mcp.txt /tmp/
RUN /bin/sh /tmp/install.sh && rm -f /tmp/install.sh /tmp/python-constraints.txt /tmp/requirements-mcp.txt

COPY LICENSE ./
COPY hpc_mcp/ ./hpc_mcp/
COPY schemas/ ./schemas/
COPY tools/check_portable_job.py tools/check_slurm_job.py ./tools/
COPY cases/portable-python/job.json cases/portable-python/program.py cases/portable-python/parameters.json ./cases/portable-python/
COPY cases/portable-python/client-example/ ./cases/portable-python/client-example/
COPY cases/portable-python/docker/start.sh /usr/local/bin/polis-slurm-test
ENTRYPOINT ["/bin/sh", "/usr/local/bin/polis-slurm-test"]
CMD ["/opt/polis-venv/bin/python", "-m", "tools.check_slurm_job"]
