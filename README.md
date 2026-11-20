# Just Do It

A local workspace for choosing one useful result, focusing on it, and picking up where you left off.

**Early preview.** Just Do It is a local personal workspace. This application version is being prepared for its first public release. The workspace, first-run setup and weekly planner support Ukrainian, Russian and English. Use the compact UA / RU / EN selector in the header; the browser remembers your choice.

Open `http://127.0.0.1:8770/?lang=uk` for Ukrainian or `?lang=en` for English. Language changes affect interface copy and dates, never your task titles, notes or other saved content. The command-line tools and legacy read-only life-map snapshot retain their existing language.

## Start your own workspace

Requires Python 3.9+ on macOS or Linux; no Python packages, AI subscription, API key or calendar account are required for local use.

```sh
python3 scripts/start_workspace.py
```

Open **http://127.0.0.1:8770**. Enter your name and confirm the timezone detected by your browser. Create a direction (a project or area of your life), describe its desired outcome, then add a task and its first step. Choose the task for Today and start a focus session. When you stop, save the outcome and next step; finishing a session does not automatically complete the task.

Your records live in `~/PersonalOS`, outside this code checkout. Run the same command again to reopen them; setup will not replace an existing profile. To choose another location or port:

```sh
python3 scripts/start_workspace.py --root /path/to/my-workspace --port 8772
```

For a new workspace use a nonexistent or empty directory. An unrelated nonempty directory is rejected. If a port is already occupied, choose another port or stop the previous server. Stop this server with Ctrl+C. Back up the entire data directory while the server is stopped; updating code must not replace it. No writes occur merely by opening first-run setup.

If a save is interrupted, use the displayed retry button. Keep the same browser tab until the result is confirmed; its draft and exact pending request survive reload. Do not create the same item again in a different tab to recover a pending save.

Calendar and chat integrations are optional and are not connected by this setup. You can add a Codex chat link using the task edit action. Automated source reading requires your own assistant/connector setup; calendar connection management is outside this first-run flow. Local Today choices never create calendar events.

## Try a fictional workspace

Requires Python 3.9+ on macOS or Linux. The application uses the Python standard library and local browser assets; no Python package installation, cloud account or model key is needed for the demo. Windows is not yet supported (`fcntl` is used for storage locking). Node is only needed for JavaScript tests; the optional 3D build toolchain is separate.

```sh
python3 scripts/demo_workspace.py
```

Open **http://127.0.0.1:8771**. The command creates a new temporary directory with fictional records and starts a loopback-only server. Stop it with Ctrl+C. It never reads an existing profile, connects to chats or publishes calendar events. Keep the printed directory if you want to reopen that demo:

```sh
python3 scripts/serve_workspace.py --root /path/printed/by/the/demo --port 8771
```

For a different timezone, pass `--timezone America/New_York` to the demo. Demo records are explicitly synthetic and are not a starting profile for real personal data. Use `start_workspace.py` for your own empty profile.

## What works

- Workstream overview, related tasks and user-supplied chat links.
- One local daily result, task edits, deferral, waiting and explicit completion.
- Manual weekly planning with task/card/session links.
- Focus sessions with saved outcomes and continuation steps.
- Thought Inbox, material links and task-linked questions/decisions.
- Revision history, conflict checks and safe retries for local writes.

Live agent statuses are unavailable without a supported runtime channel. Automatic reading/reconciliation of chats needs a separately configured assistant workflow and connector access. A fresh installation does not receive the original author's schedules, accounts or chat access. Calendar operations require separate user authorization and supplied calendar evidence. Material links are saved references, not automatically verified documents.

## Keep your data separate

`--root` points to a data workspace containing `personal/` and `.local/`; application code/assets come from this checkout. Prefer a data directory **outside** the source checkout. This repository's ignore rules also exclude personal records, generated files and common secret files. These rules do not remove anything that was already committed.

The HTTP server is intended for local use, not public internet hosting or multi-user access. No telemetry or account provisioning is included.

## Development

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.cjs
node --check web/explorer.js
git diff --check
```

Tests use isolated fictional data. Optional 3D renderer rebuild instructions are in [tools/graph3d/README.md](tools/graph3d/README.md). [Architecture](docs/architecture.md) explains the code/data boundary; [contributor instructions](AGENTS.md) cover safe development.

Licensed under [MIT](LICENSE). See [license notes](LICENSE-STATUS.md) and the [roadmap](docs/roadmap.md). Bundled third-party notices remain in [web/vendor/THIRD-PARTY-LICENSES.txt](web/vendor/THIRD-PARTY-LICENSES.txt).
