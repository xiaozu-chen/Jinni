# J I N N I

![alt text](tn.jpg)

## Charts and data

`make_chart` reads CSV files and `.xlsx` workbooks from the workspace. Excel input uses the first worksheet; legacy `.xls` files are not supported. Tables can contain up to 50 data rows.

Supported chart kinds are `bar`, `stacked`, `line`, `pie`, and `donut`. Use `secondary_y_column` with a line chart when a series needs its own scale. Narrow single-series bars use compact value labels. The chart palette is based on the [Okabe–Ito Color Universal Design palette](https://jfly.uni-koeln.de/color/), with different dash patterns for line series so color is not the only cue.

Chart export commands save files beside the HTML chart:

- `/png [chart] [light|dark] [WIDTHxHEIGHT]`
- `/svg [chart]`
- `/pdf [chart]`
- `/export-all [png|svg|pdf]` (omit the format to export every chart to all three formats)

`fetch_table(url, table_index)` saves a public HTML table as a CSV and records the source URL, fetch time, and content hash in a provenance sidecar. Charts made from that CSV retain the source and date.

To bridge data from MCP, configure an allowlisted server tool that returns JSON with `columns` and `rows`, then use `/mcp-table <server> <tool> [JSON arguments]`. The repository includes a local sales fixture at `tests/fixtures/chart_data_server.py`; add it as an MCP server in `Settings.mcp_servers` to try `/mcp-table fixture get_table {"dataset":"sales"}`.

MCP tool calls are checked against each server's advertised input schema before they are sent. Tools also must be explicitly allowlisted in `Settings.mcp_servers`.

## Memory maintenance

During the exit review, Jinni flags facts that look similar to saved facts so you can decide whether to keep both or skip the new one. Use `/prune DAYS` to review session notes older than that many days; Jinni shows a preview and asks before deleting. Saved facts are not pruned.

## CLI shortcuts

Use `/help` for the command list, `/config` to inspect non-sensitive effective settings, and `/undo` to remove the latest chat turn from conversation history. `/undo` does not reverse file or other tool side effects.

During a chat, Jinni can ask a clarifying question and keep a session task list with `task_list` actions `list`, `add`, `done`, `remove`, and `clear`; `/tasks` displays it. At the configured step limit, it asks before continuing another block of tool calls.

## Project inspection tools

The read-only coding tools include ranged `read_file`, `search_files`, `find_files`, `code_outline`, and `project_tree`. Searches skip common generated folders, reject unsafe regex patterns, and cap their scan and output sizes.

Use `check_python(path, checker)` for a bounded syntax check, Ruff lint, or Pyright type check. Ruff and Pyright are optional local tools; checks time out, cap their output, and never apply fixes.

## Read-only MCP server

Run `python mcp_server.py` from the project directory as an MCP stdio server. It exposes only `list_files`, `read_file`, and `recall`; file access stays inside the workspace. It has no write, web, or delete tools.
