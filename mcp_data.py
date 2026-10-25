from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from urllib.parse import quote, urlencode

from tools.provenance import write_csv_provenance
from tools.workspace import mark_written, safe_path
from tools.web import MAX_TABLE_CSV, MAX_TABLE_ROWS


def table_result_csv(result) -> bytes:
    if getattr(result, "is_error", False):
        raise ValueError("the MCP tool returned an error")
    payload = getattr(result, "structured_content", None)
    if isinstance(payload, dict) and not ("columns" in payload or "rows" in payload):
        payload = payload.get("result")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if not isinstance(payload, dict) or not ("columns" in payload or "rows" in payload):
        blocks = getattr(result, "content", None) or []
        texts = [getattr(block, "text", "") for block in blocks if isinstance(getattr(block, "text", None), str)]
        if len(texts) != 1:
            raise ValueError("the MCP tool must return a structured table or one JSON text block")
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError:
            raise ValueError("the MCP tool result is not JSON table data") from None
    if not isinstance(payload, dict):
        raise ValueError("the MCP result must be an object with columns and rows")
    columns, rows = payload.get("columns"), payload.get("rows")
    if (not isinstance(columns, list) or not columns or len(columns) > 100
            or any(not isinstance(name, str) or not name.strip() for name in columns)
            or len(set(columns)) != len(columns)):
        raise ValueError("the MCP table needs unique, non-empty column names")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_TABLE_ROWS:
        raise ValueError(f"the MCP table needs 1 to {MAX_TABLE_ROWS} data rows")

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for index, row in enumerate(rows, 1):
        if isinstance(row, dict):
            if any(name not in row for name in columns):
                raise ValueError(f"MCP table row {index} is missing a column")
            values = [row[name] for name in columns]
        elif isinstance(row, (list, tuple)) and len(row) == len(columns):
            values = row
        else:
            raise ValueError(f"MCP table row {index} must match the columns")
        writer.writerow(["" if value is None else value for value in values])
    data = output.getvalue().encode("utf-8")
    if len(data) > MAX_TABLE_CSV:
        raise ValueError("the MCP table is too large to save")
    return data


async def export_mcp_table(manager, server_name: str, tool_name: str,
                           arguments: dict[str, object]) -> str:
    server = manager.servers.get(server_name)
    if server is None:
        raise ValueError(f"no MCP server called '{server_name}' is configured")
    if tool_name not in server.cfg.tools:
        raise ValueError(f"'{tool_name}' is not allowlisted for MCP server '{server_name}'")
    if not any(tool.name == tool_name for tool in server.tools):
        raise ValueError(f"MCP server '{server_name}' does not offer '{tool_name}'")
    result = await server.call_raw(tool_name, arguments)
    data = table_result_csv(result)
    args_text = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(args_text.encode("utf-8")).hexdigest()[:8]
    dataset = str(arguments.get("dataset", "data"))
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{server_name}-{tool_name}-{dataset}").strip("-").lower()[:50]
    path = safe_path(f"{stem}-{digest}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    source = f"mcp://{quote(server_name)}/{quote(tool_name)}"
    if arguments:
        source += "?" + urlencode({key: str(value) for key, value in arguments.items()})
    record = write_csv_provenance(path, data, source, 0)
    mark_written(path)
    return f"Saved MCP table to {path.name} ({record['fetched_at'][:10]}, {len(data)} bytes). Use make_chart with this CSV to chart the source data."
