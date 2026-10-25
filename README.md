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

## Memory maintenance

During the exit review, Jinni flags facts that look similar to saved facts so you can decide whether to keep both or skip the new one. Use `/prune DAYS` to review session notes older than that many days; Jinni shows a preview and asks before deleting. Saved facts are not pruned.
