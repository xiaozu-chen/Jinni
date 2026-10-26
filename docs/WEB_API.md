# Local web API

Install the API dependencies and start the backend from the repository root:

```powershell
python -m pip install -r requirements-web.txt
python main.py --run-as web
```

The API listens on `http://127.0.0.1:8765`. It is intended for one local user and has no login or token. Keep it bound to `127.0.0.1`; do not expose it to other computers. The web UI is a separate project.

All request and response bodies use JSON. A chat request starts in the background and returns immediately. Poll `/api/events` for progress and replies. If Jinni requests approval or asks a question, answer it at the interaction endpoint, then continue polling.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | Check that the API is running. |
| `GET` | `/api/state` | Read the busy state, active project, reasoning mode, and model. |
| `GET` | `/api/workspace` | List registered projects and isolated chat sessions, plus the active session ID. |
| `POST` | `/api/sessions` | Create and activate a chat, optionally in a project, with `{"project_id":"..."}`. |
| `POST` | `/api/sessions/{id}/activate` | Switch to an existing chat session. |
| `PATCH` | `/api/sessions/{id}` | Rename a chat with `{"title":"..."}`. |
| `DELETE` | `/api/sessions/{id}` | Delete a chat; deleting the active chat activates or creates a replacement. |
| `GET` | `/api/sessions/{id}/export` | Export a chat's visible messages and text attachments. |
| `POST` | `/api/sessions/{id}/edit` | Truncate the conversation from a user message using `{"message_index":0}`; returns that message and its attachments. |
| `POST` | `/api/projects/{id}/activate` | Activate a project and one of its chats. |
| `DELETE` | `/api/projects/{id}` | Remove a project and its sessions from the API; the folder on disk is retained. |
| `GET` | `/api/model` | Read the model name and current context-window usage. |
| `GET` | `/api/thinking` | Read the current or most recent reasoning text and whether it is active. |
| `GET` | `/api/actions?after=0` | Read recent tool calls and agent status events. |
| `GET` | `/api/permission` | Read the pending approval, if any. |
| `POST` | `/api/permission/{id}` | Approve, reject, or remember a pending approval with `{"decision":"approve"}`, `{"decision":"reject"}`, or `{"decision":"always"}`. |
| `POST` | `/api/reasoning-mode` | Select `auto`, `thinking`, or `fast` with `{"mode":"auto"}`. |
| `POST` | `/api/project/select` | Select a folder with `{"path":"C:\\work\\project"}`. |
| `POST` | `/api/project/close` | Close the selected project. |
| `POST` | `/api/chat` | Start a chat turn with `{"message":"Hello","attachments":[{"name":"notes.txt","content":"...","mime_type":"text/plain"}]}`. Supports up to 12 text attachments, 100,000 characters each, and 300,000 characters combined. |
| `GET` | `/api/events?after=0` | Get events newer than the supplied event ID. |
| `POST` | `/api/interactions/{id}` | Answer an approval or question with `{"answer":"y"}`. |
| `GET` | `/api/session` | Read user and assistant messages. |
| `DELETE` | `/api/session` | Clear the conversation. |

Events include `user_message`, agent progress events such as `status`, `thinking_delta`, `action_stream`, `action_started`, `action_completed`, `responder_start`, and `text_delta`, `interaction_required`, `error`, `turn_complete`, and `project_changed`. Step-limit interactions use the `continuation` kind and accept `continue` or `abort` at `/api/interactions/{id}`. Approval interactions expose an `a=always allow` choice only when it is available; `/api/permission/{id}` rejects `always` otherwise. `action_stream` contains only the tool name, call ID, and optional added/deleted line counts; streamed tool arguments are never sent to the web client. After a turn uses tools, the configured model is called again in a Responder role with the same conversation context to produce the final user-facing summary. Event history is held in memory and bounded to the most recent 1,000 events; action history is bounded to the most recent 100 entries. The thinking endpoint retains the latest 100,000 characters.

The reasoning mode can be changed only while Jinni is idle. `auto` uses the configured thinking classifier/default, `thinking` forces reasoning on, and `fast` forces it off. Permission decisions are available only for pending approval interactions; `always` is accepted only when the approval offers a remember option. Questions and other interactions continue to use `/api/interactions/{id}`.
