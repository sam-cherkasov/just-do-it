# Just Do It roadmap

This checkout is the source of reusable application code. Profiles and integration accounts live outside it. Continue product improvements here; keep personal context out of code changes and test fixtures.

## Implemented

- Ukrainian, Russian and English workspace, onboarding and planner; persistent header language selector.

- Shared task, planner, focus-session and user-supplied chat identities.
- Today: one explicit daily result, protected task corrections, deferral, waiting and completion.
- Return to work: saved next steps, materials, thought Inbox and task-linked questions.
- First run: empty external profile, own directions/tasks and focus without calendar or AI accounts.
- Local storage with revision history, conflict checks and retryable requests. Multi-record creation is resumable rather than a single filesystem transaction.

## Release preparation

- Verify onboarding on an independent clean Linux host; macOS has been exercised. Windows is not supported yet.
- Review distributed files, dependencies and history before publishing application code.
- Add CI, release/update instructions and a short fictional demonstration.
- Localize the legacy read-only snapshot and CLI/low-level diagnostic messages if needed.

## Product improvements

1. Time and replanning: bring explicit capacity and optional calendar evidence into the shared UI without turning empty time into assumed availability.
2. Results and review: connect session reports to outcomes and help revise priorities without inferring completion from missing activity.
3. Agent visibility, conditional on a supported channel: show actual runtime signals and attention requests, distinguish unknown/stale status and open the originating chat. Chat recency is not a live status.

Direct agent control, additional providers, mobile access and hosted/multi-user deployment require separate design and validation. They are not bundled capabilities or permission to take external actions.
