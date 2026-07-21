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
3. Set the same version in `VERSION`.
4. Commit the release metadata through a pull request.
5. Create and push an annotated tag, for example `v0.1.0`.
6. GitHub Actions validates the tag and creates a GitHub release with generated
   notes.

The release workflow creates GitHub releases but does not publish a package
registry artifact. Installation remains explicit through the repository's safe
CLI and Hermes scripts.
