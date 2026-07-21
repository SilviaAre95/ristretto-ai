# Open-source Readiness Audit

Audit date: 2026-07-18

## Verdict

**The committed public tree is publication-ready when both verification gates
pass.** No live Slack, GitHub, OpenAI, Anthropic, or Linear token is present in
tracked files. Personal runtime state and operational history remain local and
ignored.

The existing private repository history may contain maintainer email metadata
and earlier personal operational documents. Do not push that history. Export a
clean snapshot with `scripts/export-public.sh`, review it, configure a
privacy-safe Git identity, and create the public repository from that snapshot.
The private checkout also installs `.githooks/pre-push`, which rejects every
ref descended from the known private root commit. The hook is defense in depth;
it does not replace the clean-snapshot export.

## Already safe

- Secret-shaped token scan of tracked files: clean.
- Secret-shaped token scan of reachable git patches: clean.
- Runtime cron state/output, lock files, heartbeat files, local state, issue
  exports, personal plans, `.env`, and `HANDOVER.md` are ignored.
- Deterministic tests do not require live Slack or Linear credentials.
- An MIT license, release metadata, CI, and development bootstrap now exist.
- A versioned public instance/provider/repository/flow schema and validated CLI
  exist.
- The idempotent Hermes installer preserves existing config, credentials,
  persona, jobs, and unrelated skills; service installation requires an
  explicit flag.
- A clean-snapshot exporter prevents accidental publication of private Git
  history.

## Release gate

1. Commit the intended release tree.
2. Run `make check` and `make public-check`.
3. Export to a new staged repository with
   `scripts/export-public.sh <absolute-path>`.
4. Inspect the snapshot and rerun both gates there after bootstrapping the dev
   environment.
5. Configure a public/noreply Git identity and create the first public commit.
6. Only then create and push the GitHub repository.
