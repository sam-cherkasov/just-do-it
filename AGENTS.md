# Contributor instructions

Read README.md and docs/architecture.md. This checkout contains reusable application code, not a personal profile. User data belongs in a separate data root; never search, copy or publish personal records, chat exports, credentials or local generated views as part of a code change.

Use Python 3.9+ standard library, four-space indentation and focused modules. `personal_os/` owns validation/storage, `scripts/` exposes commands and servers, `web/` owns the UI, `tests/` uses isolated synthetic roots. Use the CLI for authorized record mutations; do not edit canonical JSON directly. Run the Python and JavaScript tests listed in README, JS syntax checks and `git diff --check`. Review changed UI with fictional data only.

Keep facts, user reports, suggestions and explicit choices separate. Missing activity is unknown. A session outcome or resolved question does not automatically complete its task. Thought capture does not switch focus. Existing manual edits and snapshots must survive background updates. Preserve revision checks, exact retries and user-controlled fields.

Do not imply that live agent status or background chat synchronization is available without a verified source. No automatic calendar publication, messages, task execution, Git commits or pushes without the user's instruction. Do not broaden the loopback server into a publicly reachable service without a separate design and explicit authorization.
