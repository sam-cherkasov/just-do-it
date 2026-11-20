# Application and data boundary

One application checkout can run against a separate data workspace:

```text
application checkout             private data workspace
  personal_os/                     personal/config.json
  scripts/                         personal/records/
  web/                             personal/diary/
  tests/                           personal/reflections/
                                   .local/
```

`python3 scripts/serve_workspace.py --root <data-workspace>` reads records from that workspace while serving assets and dispatching CLI writes from this application checkout. No symlink to a personal profile is needed. Back up the data directory before adopting a new application version. Configuration includes the timezone and an optional-workflow calendar identity; it is not authentication and no provider credentials are bundled.

The Python Engine validates commands and stores revisioned records under a local file lock. Writes are atomic per record; request IDs support exact retries. Sources, checks and semantic reconciliation remain separate evidence. Manual day choices, planner cards, focus snapshots and personal notes have their own identities and do not silently mutate each other's status.

The browser talks to a loopback HTTP server with Host/Origin/token checks for writes. JavaScript renders text with DOM text nodes. The server only serves allowlisted application assets, not arbitrary workspace files. This is a single-user local application, not a hardened hosted service.

The source checkout intentionally contains no personal data, previous private Git history, local integration schedules, private chat links, screenshots, or imported planning documents. The export receipt records relative paths and hashes of the reviewed candidate files; it is a migration receipt rather than a signature or a complete security audit.

`start_workspace.py` serves first-run setup for a new empty data directory, then reopens the same profile on subsequent runs. Calendar identity is optional; no live calendar snapshot is accepted without a configured account. Setup requires explicit name/timezone submission and cannot silently replace an existing profile.

The `create-workstream` command creates an area node and direction. `create-task` creates a task and appends its identity to the latest direction under the engine lock. These are resumable multi-record operations, not one filesystem transaction: deterministic child request IDs let an exact retry finish an interrupted link without duplicating records. An intermediate area or unassigned task can remain until that retry. Existing fields on the direction are preserved, and no day choice or focus session is created implicitly.

Known portability work remains: legacy snapshot/CLI localization, supported integration setup, release/update tooling and Windows support. The current demo uses a new synthetic workspace; never mix it with a real profile. Automated first-use checks and a macOS browser walkthrough are available; Linux first-use validation on a separate clean host remains pending.

The workspace and planner share an offline three-language interface catalog (`web/i18n-catalog.js`) and bootstrap (`web/i18n.js`). The bootstrap translates the static shell once before rendering; dynamic interface copy uses explicit translation calls. User records are never passed through the translator. Language is stored per browser origin with an explicit `lang=uk|ru|en` URL override. Switching reloads the current route and keeps board IDs; unfinished saves prevent switching. Existing session-storage drafts survive the reload.
