import asyncio
import json
from types import SimpleNamespace

import pytest

from config import McpServerConfig
from mcp_data import export_mcp_table, table_result_csv
from tools.provenance import read_csv_provenance
from tools.charts import make_chart


def result(payload):
    return SimpleNamespace(structured_content=payload, content=[], is_error=False)


def test_mcp_table_payload_becomes_csv_bytes():
    payload = {"columns": ["month", "sales"], "rows": [["Jan", 10], ["Feb", 15]]}

    assert table_result_csv(result(payload)) == b"month,sales\r\nJan,10\r\nFeb,15\r\n"


def test_mcp_json_text_becomes_csv_bytes():
    payload = json.dumps({"columns": ["k", "v"], "rows": [{"k": "a", "v": 1}]})
    text_result = SimpleNamespace(
        structured_content=None,
        content=[SimpleNamespace(text=payload)],
        is_error=False,
    )

    assert table_result_csv(text_result) == b"k,v\r\na,1\r\n"


def test_mcp_wrapped_json_result_becomes_csv_bytes():
    payload = json.dumps({"columns": ["month", "sales"], "rows": [["Jan", 10]]})
    wrapped_result = SimpleNamespace(
        structured_content={"result": payload},
        content=[SimpleNamespace(text=payload)],
        is_error=False,
    )

    assert table_result_csv(wrapped_result) == b"month,sales\r\nJan,10\r\n"


@pytest.mark.parametrize("payload", [
    {"columns": ["x", "x"], "rows": [[1, 2]]},
    {"columns": ["x"], "rows": []},
    {"columns": ["x", "y"], "rows": [[1]]},
    {"columns": ["x"], "rows": [[1]] * 51},
])
def test_mcp_table_rejects_bad_shapes(payload):
    with pytest.raises(ValueError):
        table_result_csv(result(payload))


class FakeServer:
    def __init__(self, payload, allowed=("get_table",)):
        self.cfg = McpServerConfig(name="fixture", command="python", tools=allowed)
        self.tools = [SimpleNamespace(name="get_table")]
        self.payload = payload
        self.calls = []

    async def call_raw(self, tool, arguments):
        self.calls.append((tool, arguments))
        return result(self.payload)


def test_export_mcp_table_saves_hash_checked_provenance_and_charts_it(workspace):
    server = FakeServer({"columns": ["month", "revenue"], "rows": [["Jan", 10], ["Feb", 20]]})
    manager = SimpleNamespace(servers={"fixture": server})

    message = asyncio.run(export_mcp_table(manager, "fixture", "get_table", {"dataset": "sales"}))

    assert "Saved MCP table" in message
    csv_path = next(workspace.glob("fixture-get_table-sales-*.csv"))
    record = read_csv_provenance(csv_path)
    assert record["source_url"].startswith("mcp://fixture/get_table?")
    assert make_chart(csv_path.name, "month", "revenue").startswith("Saved")
    chart = next((workspace / "charts").glob("*.html"))
    chart_text = chart.read_text(encoding="utf-8")
    assert "mcp://fixture/get_table" in chart_text
    assert "unverified" not in chart_text
    assert server.calls == [("get_table", {"dataset": "sales"})]


def test_mcp_export_refuses_non_allowlisted_tools(workspace):
    server = FakeServer({"columns": ["x"], "rows": [[1]]}, allowed=())
    manager = SimpleNamespace(servers={"fixture": server})

    with pytest.raises(ValueError, match="not allowlisted"):
        asyncio.run(export_mcp_table(manager, "fixture", "get_table", {}))

    assert not list(workspace.glob("*.csv"))
