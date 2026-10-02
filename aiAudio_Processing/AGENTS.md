# AGENTS.md (root)

Cross-cutting instructions for agents working anywhere in the Live Sound Radar
repository. Component subfolders (e.g. capture/) have their own AGENTS.md with
stack-specific stack, commands, and style rules — this file does not repeat
or override those; it covers what applies regardless of which component you're in.

## Project overview
- C++ captures/resamples audio; Python performs local inference; a TypeScript
  frontend/dashboard consumes results. See each component's own AGENTS.md.
- Member 1 also owns cloud/analytics/ and sql/ when assigned Snowflake work.
- [Add other component owners/paths here as they're established.]

## Implementation workflow
1. Inspect Git status, existing code, and relevant contracts before editing.
2. Make a short checklist for substantial work, then implement a runnable increment.
3. Preserve shared interfaces; report conflicts rather than silently redesigning them.
4. Build, run focused tests, inspect the diff, and fix relevant failures.
5. Report changes, actual verification, and blockers; distinguish mocks from live tests.

Continue independent work when credentials or a teammate's component are missing.
Resolve routine implementation choices without repeatedly requesting confirmation.

## Parallel agents
- Delegate independent substantial work when subagent tools are available.
  Default to two helpers; use up to four only with clearly separate responsibilities.
- Give each helper a goal, owned files, interface constraints, and acceptance checks.
  Pass relevant instructions; do not assume shared conversation context.
- One writer per file. Use separate build directories for concurrent builds.
- The primary owns shared headers/build changes unless explicitly reassigned;
  it reviews helpers' changes and builds/tests the integrated result.
- Good split: divide by component, or by lifecycle/conversion/tests within one.
- If delegation is unavailable, continue sequentially and report that limitation.

## Boundaries and handoff
- Edit assigned files freely; coordinate changes to shared contracts, dependency
  versions, language/runtime standards, or another member's directories.
- Preserve user/teammate changes. Do not switch a shared checkout's branch while
  another agent is working. Commit/push only as authorized by the task.
- Never commit secrets, .env, raw recordings, or generated build artifacts.
- Handoff: what changed, commands/results, and remaining unverified behavior.
- These rules do not reassign teammates' work or dictate another component's
  language-specific style; see that component's own AGENTS.md for those.

## More
- For user-facing setup and commands, see README.md and each component's README.
- For capture/C++ specifics, see capture/AGENTS.md and docs/audio-contract.md.
