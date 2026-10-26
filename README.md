# J I N N I

![alt text](tn.jpg)

## Development setup

Use Python 3.11 on Windows, then install the checked-in environment and quality tools:

```powershell
python -m pip install -r requirements-lock.txt -r requirements-dev.txt
pre-commit install
```

Install Jinni as a command with `python -m pip install -e .`. Copy `settings.example.toml` to `settings.toml` to override defaults; `JINNI_SETTINGS` can point to another TOML file. Unknown keys and values with the wrong type are rejected at startup. MCP server allowlists can still be managed in `mcp_servers.json`.

Run `python -m pytest`, `ruff check .`, and `pyright` before opening a pull request. CI runs the same checks on pushes and pull requests.

## Model evaluation

Run `python -m eval_harness` against the configured local chat server to measure expected tool selection. The default matrix compares thinking on/off and menus of 8/all tools. Use `--models qwen3,qwen3.5`, `--menu-sizes 5,10,all`, or `--prompts prompt_variants.json` to compare named system prompts from a JSON object. `--server-context 16384` adds a context-size label; restart the local server with the matching context before each run. Cases and expected calls live in `eval_cases.json`; tools absent from a smaller menu are skipped so the score measures selection among available tools.

## Charts and data

`make_chart` reads CSV files and `.xlsx` workbooks from the workspace. Excel input uses the first worksheet; legacy `.xls` files are not supported. Tables can contain up to 50 data rows.

Supported chart kinds are `bar`, `stacked`, `line`, `pie`, and `donut`. Use `secondary_y_column` with a line chart when a series needs its own scale. Narrow single-series bars use compact value labels. The chart palette is based on the [Okabe–Ito Color Universal Design palette](https://jfly.uni-koeln.de/color/), with different dash patterns for line series so color is not the only cue.

Chart export commands save files beside the HTML chart:

- `/png [chart] [light|dark] [WIDTHxHEIGHT]`
- `/svg [chart]`
- `/pdf [chart]`
- `/export-all [png|svg|pdf]` (omit the format to export every chart to all three formats)

`fetch_table(url, table_index)` saves a public HTML table as a CSV and records the source URL, fetch time, and content hash in a provenance sidecar. Charts made from that CSV retain the source and date.

CSV files created or edited with Jinni also get a hash-checked sidecar, so charts keep the "typed by Jinni, numbers unverified" notice after a restart.

To bridge data from MCP, configure an allowlisted server tool that returns JSON with `columns` and `rows`, then use `/mcp-table <server> <tool> [JSON arguments]`. The repository includes a local sales fixture at `tests/fixtures/chart_data_server.py`; configure it in `mcp_servers.json` to try `/mcp-table fixture get_table {"dataset":"sales"}`. The file has a top-level `servers` list; each entry can set `name`, `command`, `args`, `env`, `tools`, `remember`, `call_timeout`, and `mode`. If the file is missing, Jinni uses the built-in settings; an invalid file is reported and ignored.

MCP tool calls are checked against each server's advertised input schema before they are sent. Tools also must be explicitly allowlisted in `mcp_servers.json` or the built-in settings.

Use `/replay start NAME` to record model requests and expected tool choices locally, `/replay stop` to finish, and `/replay run NAME [MODEL]` to compare choices against a model. Replays store conversation context under `workspace/.jinni/replays/`; only start recording when that local data is appropriate to save. Replay never runs the model's selected tools.

With a managed project selected, Jinni also offers `search_workspace_files` for semantic search across bounded, readable project files. It skips generated and secret files, reports source line ranges, and falls back to keyword matching if the embedding service is unavailable.

Jinni only fetches URLs that the user supplied or that appeared in a web-search result during the session. The existing per-domain approval still applies.

## Memory maintenance

During the exit review, Jinni flags facts that look similar to saved facts so you can decide whether to keep both or skip the new one. It also offers old facts for deletion; keeping one snoozes that prompt for another year. Use `/prune DAYS` to review session notes older than that many days; Jinni shows a preview and asks before deleting. Saved facts are not pruned automatically.

Use `/memory facts`, `/memory events`, or `/memory search TEXT` to filter saved memories. Each item shows its source session; memory facts added to the system prompt are capped at 2,400 characters.

Run `python bench_embed.py` with the configured embedding service running to compare related and unrelated similarity scores; it suggests a floor only when the sample ranges do not overlap.

The initial `nomic-embed-text-v1.5.Q8_0.gguf` calibration on 2026-10-25 scored related pairs at 0.575, 0.561, and 0.550; unrelated pairs scored 0.418, 0.473, and 0.420. The highest unrelated score was 0.473 and the lowest related score was 0.550, so the midpoint floor is 0.512. `min_similarity` now uses that value; this small set is a starting check, not a broad relevance evaluation.

## CLI shortcuts

Use `/help` for the command list, `/config` to inspect non-sensitive effective settings, `/stats` for session usage totals, `/save [NAME]` and `/load NAME` for bounded transcripts in `workspace/transcripts/`, and `/undo` to remove the latest chat turn from conversation history. `/undo` does not reverse file or other tool side effects.

Press the up arrow at the interactive prompt to recall earlier input.

During a chat, Jinni can ask a clarifying question and keep a SQLite-backed task list with `task_list` actions `list`, `due`, `add`, `done`, `remove`, and `clear`; added tasks can have an ISO due date, `/tasks` displays the list, and overdue tasks appear at startup. Clearing the list asks for confirmation. At the configured step limit, Jinni asks before continuing another block of tool calls.

## Project inspection tools

The read-only coding tools include ranged `read_file`, `search_files`, `find_files`, `code_outline`, and `project_tree`. Searches skip common generated folders, reject unsafe regex patterns, and cap their scan and output sizes.

Use `check_python(path, checker)` for a bounded syntax check, Ruff lint, or Pyright type check. Ruff and Pyright are optional local tools; checks time out, cap their output, and never apply fixes.

Launch `jinni --project PATH` to copy a repository into `workspace/projects/` before Jinni can edit it. Jinni loads that copy's `JINNI.md` as project guidance; generated folders such as virtual environments and caches are skipped. Without `--project`, the regular workspace remains active.

## Read-only MCP server

Run `python mcp_server.py` from the project directory as an MCP stdio server. It exposes only `list_files`, `read_file`, and `recall`; file access stays inside the workspace. It has no write, web, or delete tools.
