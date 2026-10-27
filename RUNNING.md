# Running Jinni

Jinni is a Python 3.11 CLI that connects to a local OpenAI-compatible chat server. It expects the chat server at `127.0.0.1:8080` and, when semantic memory is enabled, an embedding server at `127.0.0.1:8081`.

## Set up the environment

From the repository root in PowerShell:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt -r requirements-dev.txt
python -m pip install -e .
if (-not (Test-Path settings.toml)) { Copy-Item settings.example.toml settings.toml }
```

Edit `settings.toml` for your model names or server URLs. It is ignored by Git. `JINNI_SETTINGS` can point Jinni at a settings file elsewhere.

## Start the local model servers

Start the chat server in one terminal, replacing the model path with your local model:

```powershell
llama-server -m C:\models\qwen3.5.gguf -c 16384 --jinja --host 127.0.0.1 --port 8080 -ngl 99
```

If semantic memory is enabled, start the embedding server in another terminal:

```powershell
llama-server -m C:\models\nomic-embed-text-v1.5.Q8_0.gguf --embedding --pooling mean -c 2048 -ub 2048 -np 1 -ngl 0 --host 127.0.0.1 --port 8081
```

You can instead configure `embed_server_command` and `embed_server_args` so Jinni manages the embedding process. Set `embed_enabled = false` when you do not want semantic memory.

## Run Jinni

From the repository root:

```powershell
python main.py --run-as cli
```

Or run `python -m interface.cli.jinni`. Type `exit` to leave. `/help` lists the CLI commands. Use `/project PATH` to work on a managed copy of a repository; without a selected project, Jinni uses its regular `workspace` folder.

To run the web API instead, install its dependencies and start it with:

```powershell
python -m pip install -r requirements-web.txt
python main.py --run-as web
```

The API listens on `127.0.0.1:8765`. For the Tauri desktop app, keep this backend running in the background, then launch the app. The desktop executable does not start or bundle the Python backend. See [the web API guide](docs/WEB_API.md).

The Tauri UI imports a selected folder into `workspace/projects/` as an isolated, Jinni-managed copy. Agent edits and Git checkpoints stay in that copy; the original folder is not modified. Use **Review changes** in the chat header to compare edits with the imported baseline and download the diff. **Apply all N files to source** applies every eligible file in the current review; the confirmation lists those files. Apply is rejected if the working copy changes after review or any source file conflicts with the imported baseline. Binary files, files larger than 1 MB, and diffs beyond the display limit need to be reviewed and applied with Git or another file tool directly.

While a turn is running, use **Stop** to ask Jinni to stop at the next safe boundary. A pending approval is declined, newly proposed tools are skipped, and an already-running tool is allowed to finish before the turn stops; stopping does not interrupt an active shell or file operation.

Enter `/help` in the CLI for the current slash-command list. Use `/project PATH` to work on an isolated project copy.

Thinking is off by default. `/think` toggles a manual override for the current session. The read-only `delegate` helper is disabled by default; enabling `subagents_enabled` in `settings.toml` exposes it.

Approval modes are session-only: `/mode ask` uses approval prompts, while `/mode auto-edit` skips prompts only for checkpointed edits in the active managed project. Full Access is disabled by default. To enable it, add `allow_full_access = true` to `settings.toml`; the CLI and web UI then show the warning and require typing `FULL ACCESS`. It expires after 20 tool calls or 30 minutes, and `/safe` or Ctrl+C reverts it. Web, MCP, and saved-memory results taint the session and turn Full Access off. In the web UI, approval-bypass modes are available only when the selected folder is a Jinni-managed project with reversible Git checkpoints; arbitrary folders remain in Ask mode.

To choose thinking automatically, run a small OpenAI-compatible chat model on a separate local endpoint (port 8082 by default), then set `thinking_classifier_model` to the model name served there and `thinking_classifier_base_url` to that endpoint in `settings.toml`. The classifier sees only the latest user message and must answer `on` or `off`; if it is unavailable or returns an invalid label, Jinni uses `thinking_default`. `/think on` and `/think off` set a session override; `/think auto` returns control to the classifier.

## Verify changes

Run the checks from the repository root:

```powershell
python -m pytest
ruff check .
pyright
```

For the local subagent A/B evaluation, make sure the chat server is running and run:

```powershell
python -m bench.subagent_eval
```

This compares the same research tasks with delegation off and on. It does not change the normal `subagents_enabled` setting.

## Repository notes

- Application modules are grouped into responsibility folders such as `runtime/`, `memory/`, `server/`, and `presentation/`. `interface/cli/` contains the command-line entry point, while `tools/` contains registered model tools.
- The local web app separates HTTP handlers, validated request models, session persistence, and MCP lifecycle into `interface/web/routes.py`, `schemas.py`, `session_store.py`, and `mcp_runtime.py`; `api.py` coordinates the runtime and ASGI lifecycle.
- `tests/fixtures/` contains local MCP servers used by integration tests.
- `workspace/`, `settings.toml`, memory databases, logs, and local replays are runtime data and are ignored by Git.
