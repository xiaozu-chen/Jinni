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
| Sessions | `POST /api/sessions`, `POST /api/sessions/{id}/activate`, `PATCH /api/sessions/{id}`, `DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/edit`, `GET /api/sessions/{id}/export` |
| Projects | `POST /api/project/select`, `POST /api/project/import`, `POST /api/project/close`, `POST /api/projects/{id}/activate`, `DELETE /api/projects/{id}` |
| Review and apply | `GET /api/projects/{id}/changes`, `POST /api/projects/{id}/apply` |
| Controls | `GET /api/model`, `GET /api/thinking`, `GET /api/mcp`, `POST /api/reasoning-mode`, `POST /api/permission-mode` |

The full request and response schemas are available from the generated OpenAPI document at `http://127.0.0.1:8765/docs` while the API is running.

## Safe project workflow

1. Import a source folder. Jinni copies it into its managed workspace and records an imported Git baseline; agent edits stay in that copy.
2. Review changes with `GET /api/projects/{id}/changes`. The response includes the changed file list, a bounded unified diff, unsupported-file information, truncation state, and a `snapshot_id`.
3. Apply with `POST /api/projects/{id}/apply` and JSON `{"snapshot_id":"…"}` from that review. Jinni rejects stale snapshots and blocks the entire apply if any source file conflicts with the imported baseline.
4. Binary files, oversized files, and truncated reviews must be applied with Git or another file tool. Stop requests wait for an already-running file or shell operation to finish.

`GET /api/events?after=N` returns events newer than event ID `N` plus the current runtime state. Clients should advance the cursor to the largest returned event ID and continue polling while `busy` is true.
