"""Summarize one partition of the public synthetic CSV fixture."""

import json
from pathlib import Path

import duckdb


with duckdb.connect(config={
    "threads": "1",
    "memory_limit": "24MB",
    "max_temp_directory_size": "0B",
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}) as connection:
    count, total, maximum = connection.execute("""
        SELECT count(*), sum(units), max(units)
        FROM read_csv('orders.csv', columns={'units': 'BIGINT'}, header=true,
                      max_line_size=1024, buffer_size=4096, parallel=false)
    """).fetchone()
result = {"rows": count, "total_units": total, "max_units": maximum, "duckdb": duckdb.__version__}
Path("summary.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="ascii")
