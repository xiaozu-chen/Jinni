# Jinni command reference

This page covers commands typed by a person in Jinni, plus the common commands used to install, run, and check the project. Model tools are listed separately because they are selected by Jinni, not typed as slash commands.

## Interactive Jinni commands

Type these at the `you >` prompt. Use `/help` in the app to see the built-in list.

| Command | What it does | What it is for |
|---|---|---|
| `/help` | Prints the interactive command list. | Find a command or check its syntax. |
| `/config` | Shows effective, non-sensitive settings and configured MCP servers. | Check which model, context, search, memory, and server options are active. |
| `/undo` | Removes the latest user turn from chat history. If that turn made a checkpointed workspace write, it also attempts to restore that write. | Back out the latest exchange and, when possible, its last managed-project write. It does not reverse external side effects. |
| `/project`, `/project list` | Lists managed projects and marks the active one. | See which copied project Jinni will work in. |
| `/project NAME` | Switches to a managed project and loads its `JINNI.md` guidance. | Choose the project workspace for project tools. |
| `/project create NAME` | Creates and activates a managed project. | Start a clean project workspace. |
| `/subtask TASK` | Summarizes the current work, clears the current conversation history, then starts a fresh context with the summary and new task. | Continue a long job when the chat context is getting crowded. |
| `/think` | Toggles thinking as a session override. `/think on` and `/think off` set it explicitly; `/think auto` returns control to the configured tiny-model classifier. | Override automatic per-request thinking selection for the current session. |
| `/parallel` | Toggles whether independent tool calls in a lap run in parallel. | Prefer faster parallel work or sequential tool execution. |
| `/tools` | Lists the tools currently visible to the model; marks tools that ask for approval. | Check what Jinni can do in the current project and configuration. |
| `/allowed` | Lists remembered approvals and whether each is saved or session-only. | Review domains currently trusted for approved fetches. |
| `/revoke DOMAIN` | Removes remembered approvals scoped to that domain. | Stop reusing a domain approval. |
| `/revoke` | Clears all remembered approvals. | Make Jinni ask again for approvals. |
| `/memory` | Lists saved facts and session notes. | Browse all saved memory. |
| `/memory facts` / `/memory events` | Lists only facts or only session notes. | Narrow the memory listing by kind. |
| `/memory search TEXT` | Searches saved memories by text or meaning. | Find a memory when you know a phrase or topic. |
| `/forget NUMBER` | Deletes the memory with that ID. | Remove one saved fact or session note. |
| `/forget all` | Asks for confirmation, then clears all saved memories. | Remove the complete memory store. |
| `/tasks` | Displays the persistent task list. | Review saved tasks and due dates. |
| `/stats` | Shows model laps, prompt/generated/total tokens, elapsed model time, and tool-call counts. | Inspect usage for this session. |
| `/replay start NAME` | Starts recording model requests, context, tool menus, and selected tool names under `workspace/.jinni/replays/`. | Save a local case for later tool-choice evaluation. Only record context that is appropriate to store. |
| `/replay stop` | Stops and closes the active replay recording. | Finish a recording cleanly. |
| `/replay run NAME [MODEL]` | Replays the recorded requests against a model and compares selected tools. It does not execute those tools. | Evaluate tool selection without repeating side effects. |
| `/save [NAME]` | Saves the current conversation as a bounded transcript in `workspace/transcripts/`; omitting the name generates one. Asks before overwriting. | Preserve useful chat context for later. |
| `/load NAME` | Loads a saved transcript into chat as background context. | Bring a previous conversation into the current session. |
| `/audit [COUNT]` | Displays recent approved tool calls; the default count is 20. | Review the local approval audit trail. |
| `/prune DAYS` | Shows session notes older than the requested number of days, then asks before deleting them. Valid range: 1–36500 days. | Review and remove old event memories while retaining recent notes. |
| `/open [CHART]` | Opens a workspace chart in the browser. For an unrecognized page, asks before opening it. | View a chart Jinni created or a named chart file. |
| `/png [CHART] [light\|dark] [WIDTHxHEIGHT]` | Exports a chart to PNG. Theme and size can be supplied in any order; omitted values use configured defaults. | Create a raster image for sharing or inserting elsewhere. |
| `/svg [CHART]` | Exports a chart to SVG. | Create a scalable vector image. |
| `/pdf [CHART]` | Exports a chart to PDF using the configured browser. | Create a print-friendly chart file. |
| `/export-all [png\|svg\|pdf\|all]` | Exports every workspace chart in the selected format; defaults to all three formats. | Batch-export charts. |
| `/mcp` | Shows MCP server status. | Check which configured servers are running. |
| `/mcp restart SERVER` | Restarts one configured MCP server. | Recover a disconnected or unhealthy server. |
| `/mcp resources [SERVER]` | Lists allowlisted resources, optionally for one server. | Discover resource URIs available from an MCP server. |
| `/mcp read SERVER URI` | Reads an allowlisted MCP resource. | Inspect resource content from a configured server. |
| `/mcp prompts [SERVER]` | Lists allowlisted prompts, optionally for one server. | Discover prompt names exposed by an MCP server. |
| `/mcp prompt SERVER NAME [JSON]` | Gets an allowlisted prompt with optional JSON-object arguments. | Ask an MCP server to expand one of its configured prompts. |
| `/mcp-table SERVER TOOL [JSON]` | Calls an allowlisted MCP tool that returns columns and rows, then saves the table as a provenance-labeled workspace CSV. Arguments must be a JSON object. | Bring structured MCP data into Jinni’s chart workflow. |
| `/recall QUERY` | Searches saved memories and prints matching results. | Quickly retrieve a past fact or session note. |
| `/reindex` | Catches up embeddings for memories that do not yet have them. | Refresh semantic memory search after model/service changes or missed embedding work. |
| `exit` / `quit` | Leaves the CLI, runs the end-of-session memory review, and stops managed services. | End a session cleanly. |

### Task-list tool actions

`/tasks` only displays the list. Jinni can manage it through the `task_list` model tool with these actions:

| Action | Purpose |
|---|---|
| `list` | Show all tasks. |
| `due` | Show tasks due today or overdue. |
| `add` | Add task text and an optional `YYYY-MM-DD` due date. |
| `done` / `complete` | Mark a task ID complete. |
| `remove` | Remove a task ID. |
| `clear` | Ask for confirmation, then clear the task list. |

## Model tools

These names are not typed at the prompt. Jinni offers the available tools to the model, which selects them when they fit the request. `/tools` shows the tools currently enabled; project tools appear when a managed project is active, and `delegate` is opt-in.

| Tool | What it does | What it is for |
|---|---|---|
| `get_current_time` | Returns the local date and time. | Answer time-sensitive questions about the current local time. |
| `calculate` | Evaluates bounded arithmetic expressions. | Do arithmetic reliably. |
| `ask_user` | Asks one short question, optionally with choices. | Resolve missing details before acting. |
| `task_list` | Lists, filters, adds, completes, removes, or clears saved tasks. | Manage the persistent task list. |
| `remember` | Saves one lasting fact after user direction or a clear lasting preference. | Keep useful user-approved context between sessions. |
| `recall` | Searches saved facts and session notes. | Retrieve relevant context from earlier sessions. |
| `forget` | Deletes one saved memory by ID. | Remove memory at the user's request. |
| `web_search` | Searches the web and returns result titles, URLs, and snippets. | Find public sources to research. |
| `fetch_url` | Reads text from a public web page, subject to URL approval. | Inspect a supplied or discovered source page. |
| `fetch_table` | Saves a selected HTML table as CSV with source and integrity metadata. | Bring source-page data into the chart workflow. |
| `search_snippets_for_chart` | Extracts explicit numeric candidates from search snippets into a provenance-labeled CSV. | Find possible chart data; verify the values against source pages because snippets are unverified. |
| `make_chart` | Builds a bar, stacked bar, line, pie, or donut chart from workspace CSV or XLSX data. | Visualize local table data. |
| `list_files` | Lists entries in a workspace folder. | See available project files. |
| `read_file` | Reads a bounded text file or line range. | Inspect project source and documentation. |
| `search_files` | Searches workspace text, optionally using a bounded regular expression. | Find code, names, or text occurrences. |
| `find_files` | Finds workspace paths by glob pattern. | Locate files by name or folder pattern. |
| `code_outline` | Lists Python classes and functions with line numbers. | Get an overview of a module before reading details. |
| `project_tree` | Prints a bounded directory tree. | Understand project layout. |
| `search_workspace_files` | Finds relevant readable project excerpts by meaning, with keyword fallback. | Search the active project semantically. |
| `write_file` | Creates or overwrites a workspace file after approval. | Create a new project file or replace one completely. |
| `edit_file` | Replaces one exact text occurrence after approval. | Make a focused edit to an existing file. |
| `apply_patch` | Validates and applies several exact replacements as one change after approval. | Make a multi-part edit while rejecting ambiguous matches. |
| `delete_file` | Moves a workspace file to `.trash` after approval. | Remove a file reversibly. |
| `run_tests` | Runs project tests in an isolated AppContainer with bounded time and output. | Check a managed project without granting the test process ordinary host access. |
| `check_python` | Runs `py_compile`, Ruff, or Pyright on one project Python file. | Check syntax, style, or types without applying fixes. |
| `delegate` | Runs one fresh-context, read-only project lookup and returns file/line pointers. | Split a narrow research question when subagents are enabled. |

## Start and setup commands

Run these in PowerShell from the repository root unless noted.

| Command | What it does | What it is for |
|---|---|---|
| `python -m venv venv` | Creates a virtual environment. | Keep project dependencies separate from system Python. |
| `venv\Scripts\Activate.ps1` | Activates the Windows virtual environment. | Make `python` and installed tools use the project environment. |
| `python -m pip install -r requirements-lock.txt -r requirements-dev.txt` | Installs pinned runtime and development dependencies. | Prepare the environment for running and checking Jinni. |
| `python -m pip install -e .` | Installs Jinni as an editable package and adds the `jinni` console command. | Run the CLI without typing the script path. |
| `if (-not (Test-Path settings.toml)) { Copy-Item settings.example.toml settings.toml }` | Creates local settings only when none exist. | Start with documented defaults while preserving an existing config. |
| `llama-server -m C:\models\YOUR_MODEL.gguf -c 16384 --jinja --host 127.0.0.1 --port 8080 -ngl 99` | Starts the local OpenAI-compatible chat server. Replace the model path and GPU layer count for your machine. | Provide the model endpoint Jinni talks to. |
| `llama-server -m C:\models\nomic-embed-text-v1.5.Q8_0.gguf --embedding --pooling mean -c 2048 -ub 2048 -np 1 -ngl 0 --host 127.0.0.1 --port 8081` | Starts the optional embedding server. | Enable semantic memory search. |
| `jinni` | Starts the installed CLI. | Normal interactive use. |
| `python jinni.py` | Starts the CLI from the source checkout. | Run without installing the console entry point. |
| `jinni --project PATH` | Copies a repository into Jinni’s managed project area and starts with it active. | Safely work on a copy of an existing repository. |
| `python jinni.py --project PATH` | Same as `jinni --project PATH`, but runs directly from the source checkout. | Start a managed project without installing the console command. |

## Test, evaluation, and maintenance commands

| Command | What it does | What it is for |
|---|---|---|
| `python -m pytest` | Runs the test suite. | Verify behavior after changes. |
| `ruff check .` | Runs Ruff lint checks. | Catch common style and correctness issues. |
| `pyright` | Runs the configured Pyright type check. | Find incompatible or unsafe types before runtime. |
| `python -m eval_harness` | Runs the tool-selection evaluation against the configured local chat server. | Compare model/tool-menu settings against expected tool choices. |
| `python coding_eval.py --models qwen3.5 --thinking off,on --tool-counts 3,all` | Runs five bounded scratch-project coding tasks with file tools and static scoring. | Compare coding behavior without executing model-generated code. |
| `python subagent_eval.py` | Runs the same three research tasks with delegation off and on. | Measure pass rate, context, tokens, time, and pointer verification before enabling subagents by default. |
| `python bench_embed.py` | Compares related and unrelated memory-embedding similarity scores. | Calibrate `min_similarity` against the configured embedding model. |
| `python bench_search.py` | Queries a fixed phrase against several public search backends and prints result counts and elapsed time. | Compare configured search-provider availability and response speed; this makes live network requests. |
| `python mcp_server.py` | Starts Jinni’s read-only MCP server over stdio. | Expose the fixed `list_files`, `read_file`, and `recall` tools to an MCP host. |
| `pre-commit install` | Installs the repository’s Git pre-commit hooks. | Run configured checks automatically before commits. |
| `python commit_script.py "MESSAGE"` | Stages all current changes with `git add -A` and commits them using the supplied message. | Use the project’s helper only after checking that every staged change belongs in the commit. |

For current defaults and local server setup, see [RUNNING.md](../RUNNING.md). For the full roadmap, see [IDEAS.md](IDEAS.md).
