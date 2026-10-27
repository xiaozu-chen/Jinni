# Local web API

Start the API from the repository root:

```powershell
python -m pip install -r requirements-web.txt
python main.py --run-as web
```

It binds to `127.0.0.1:8765`. The Tauri UI is a separate executable and polls this API; it does not start or bundle the Python process. The API accepts the desktop origins configured in `interface/web/api.py` and rejects cross-origin state changes.

## Main endpoints

| Purpose | Endpoint |
| --- | --- |
| Health, runtime state, and workspace | `GET /api/health`, `GET /api/state`, `GET /api/workspace` |
| Chat and progress | `POST /api/chat`, `POST /api/chat/stop`, `GET /api/events?after=N`, `GET /api/actions?after=N` |
| Current chat and interactions | `GET /api/session`, `DELETE /api/session`, `POST /api/interactions/{id}`, `GET /api/permission`, `POST /api/permission/{id}` |
| Sessions | `POST /api/sessions`, `POST /api/sessions/{id}/activate`, `PATCH /api/sessions/{id}`, `DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/edit`, `GET /api/sessions/{id}/export`, `GET /api/sessions/{id}/charts/{filename}` |
| Projects | `POST /api/project/select`, `POST /api/project/import`, `POST /api/project/close`, `POST /api/projects/{id}/activate`, `DELETE /api/projects/{id}` |
| Review and apply | `GET /api/projects/{id}/changes`, `POST /api/projects/{id}/apply` |
| Controls | `GET /api/model`, `GET /api/thinking`, `GET /api/mcp`, `POST /api/reasoning-mode`, `POST /api/permission-mode`, `POST /api/auto-edit/undo` |

The full request and response schemas are available from the generated OpenAPI document at `http://127.0.0.1:8765/docs` while the API is running.

## Safe project workflow

### Chats

Each chat uses a durable backend workspace under `data/chat_workspaces/`, isolated from other chats and from user projects. Research, retrieval, local artifact reads/writes, chart creation, and moving files to the workspace trash run in Auto mode without routine approval prompts. Saving downloaded table or search-snippet data and external MCP actions still ask for approval; project command execution and Full Access are unavailable in Chats. Deleting a chat does not automatically erase its workspace files.

Generated chart pages can be embedded in the assistant response with a sandboxed iframe. The chart endpoint serves only Jinni-generated chart HTML for the requested chat or project; arbitrary workspace HTML is not rendered in the app.

### Projects

1. Open a project folder. Jinni uses that selected path directly as its tool workspace and does not copy the directory.
2. Project chats default to Ask. Auto allows web search and public page reads; Auto-edit is a separate opt-in for checkpointed project file changes. Full Access requires a Jinni-managed project, the backend setting, and typed confirmation.
3. Downloaded table/snippet data, project file changes, commands, and MCP actions remain approval-gated outside their explicitly enabled modes. Older isolated projects are migrated to their recorded source path when that path still exists; previous copies are retained and not merged automatically.

`GET /api/events?after=N` returns events newer than event ID `N` plus the current runtime state. Clients should advance the cursor to the largest returned event ID and continue polling while `busy` is true.
