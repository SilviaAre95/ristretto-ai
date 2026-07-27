# Release Process

Ristretto uses Semantic Versioning and tags releases as `vMAJOR.MINOR.PATCH`.
The first planned public version is `0.1.0`.

## Before the first public release

The current private Git history must not be pushed. After committing and
passing both gates, export a history-free tree:

```bash
bash scripts/export-public.sh /absolute/path/to/ristretto-public
```

The exporter initializes a fresh repository and stages the public tree without
committing. Review it, configure a public/noreply Git identity, and make the
first public commit. Details live in
`docs/open-source-readiness.md`.

## Cutting a release

1. Run `make check` and `make public-check`.
2. Move the relevant entries from `Unreleased` in `CHANGELOG.md` into a dated
   version section.
3. If the release requires user action — persona/config template changes to
   port, new required config keys, a re-run of an installer — add an
   **Upgrade notes** subsection to that version's changelog section saying
   exactly what to do. Skills and cron propagate automatically on update;
   the persona and config templates are user-owned seeds and never do.
4. Set the same version in `VERSION`.
5. Commit the release metadata through a pull request.
6. Create and push an annotated tag, for example `v0.1.0`.
7. GitHub Actions validates the tag and creates a GitHub release with generated
   notes.

## How users update

A running install updates with one command from the clone:

```bash
make update
```

This pulls the release (`--ff-only`), re-runs the idempotent installers to
refresh symlinked assets, reports template drift, and restarts the gateway.
User-owned files (`~/.hermes/SOUL.md`, `~/.hermes/config.yaml`, credentials,
jobs) are never overwritten. When a release changed a template, the drift
report prints the diff command and the changelog's Upgrade notes say what to
port; acknowledge with `bash scripts/template-drift.sh --ack` afterwards.

The release workflow creates GitHub releases but does not publish a package
registry artifact. Installation remains explicit through the repository's safe
CLI and Hermes scripts.
