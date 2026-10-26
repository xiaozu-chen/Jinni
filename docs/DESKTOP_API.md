# Desktop API

The desktop API is a loopback-only HTTP service with server-sent events for model and tool progress. Run `python desktop_api.py` from the repository root. It listens on `127.0.0.1:8765` by default; set `JINNI_API_PORT` or pass `--port` to change the port. The first stdout line is a JSON `ready` record containing the URL and bearer token. The Tauri process should keep that token private and send it as `Authorization: Bearer <token>`.

The API starts with **no active project**. The frontend selects a directory through Tauri's native folder picker and sends its path to `/api/v1/project/select`. Jinni operates directly in that directory. Project tools are unavailable again after `/api/v1/project/close`. `checkpointing` is false for directly selected folders unless they already have Jinni's managed-project marker and Git metadata; file writes still use the existing approval flow.

All routes except `GET /api/v1/health` require the bearer token. CORS is limited to the Tauri origins and the local Vite development origin. The server binds only to loopback.

## Routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness check. |
| `GET` | `/api/v1/state` | Active project, busy state, model, and thinking mode. |
| `POST` | `/api/v1/project/select` | Activate a selected local directory directly. Body: `{"path":"C:/work/project"}`. |
| `POST` | `/api/v1/project/close` | Deactivate the project and return to no-project mode. |
| `GET` | `/api/v1/project/files?path=.&depth=3&limit=300` | Return a bounded workspace tree. |
| `GET` | `/api/v1/project/file?path=README.md` | Read a bounded text file. Paths are relative to the selected project. |
| `GET` | `/api/v1/tools` | List tool schemas currently available to the agent. Project tools appear only after folder selection. |
| `POST` | `/api/v1/tools/{name}` | Call one visible tool. Body: `{"arguments":{...}}`. Returns SSE events. |
| `POST` | `/api/v1/chat` | Start a chat turn. Body: `{"message":"..."}`. Returns SSE events. |
| `POST` | `/api/v1/chat/cancel` | Cancel the active turn and roll back its conversation messages. |
| `POST` | `/api/v1/interactions/{id}` | Answer an approval or `ask_user` interaction. Body: `{"answer":"y"}` (or the displayed choice). |
| `GET` | `/api/v1/session` | Read chat history without exposing the system prompt or tool arguments. |
| `DELETE` | `/api/v1/session` | Clear conversation history. |
| `POST` | `/api/v1/session/undo` | Remove the latest chat turn and restore a managed-project checkpoint when one exists. |
| `GET` / `PUT` | `/api/v1/thinking` | Read or set `{"mode":"on"}`, `{"mode":"off"}`, or `{"mode":"auto"}`. |
| `GET` | `/api/v1/stats` | Session timing, token counts, and tool-call counts. |
| `GET` | `/api/v1/mcp` | Configured MCP server status. |
| `POST` | `/api/v1/mcp/restart` | Restart one MCP server or all servers. Body: `{"server":"name"}` or `{}`. |
| `GET` | `/api/v1/mcp/{server}/resources` | List the server's allowlisted resource URIs. |
| `POST` | `/api/v1/mcp/{server}/resources/read` | Read an allowlisted resource. Body: `{"uri":"..."}`. |
| `GET` | `/api/v1/mcp/{server}/prompts` | List the server's allowlisted prompts. |
| `POST` | `/api/v1/mcp/{server}/prompts/{name}` | Expand an allowlisted prompt. Body: `{"arguments":{...}}`. |
| `GET` | `/api/v1/memories?limit=100` | List saved facts and events. |
| `POST` | `/api/v1/memories/search` | Search memories. Body: `{"query":"...","limit":5}`. |
| `DELETE` | `/api/v1/memories/{id}` | Delete one saved memory. |
| `GET` | `/api/v1/tasks?due=true` | List tasks, or only due tasks. |
| `POST` | `/api/v1/tasks` | Add, complete, remove, or clear tasks with `action`; clearing requires `confirmed: true`. |

## Server-sent events

Each event uses its type as the SSE event name and repeats it in the JSON data:

```text
event: text_delta
data: {"type":"text_delta","text":"Hello"}
```

Chat streams may contain `status`, `thinking_start`, `thinking_delta`, `thinking_end`, `text_delta`, `text_end`, `interaction_required`, `tool_result`, `error`, `turn_cancelled`, and `turn_complete`. When an `interaction_required` event arrives, POST the user's answer to its interaction route while keeping the SSE stream open. Only one chat or direct tool operation can run at a time.
