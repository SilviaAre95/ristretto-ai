# Security Policy

## Supported versions

Ristretto has not published its first stable release. Security fixes currently
target the latest commit on `main`.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities or suspected secret exposure.
Once the GitHub repository is created, use GitHub private vulnerability
reporting. Until then, contact the maintainer through the private channel where
you received access to the project.

Never include live credentials, personal data, private logs, or exploit data
in a public report.

## Operational limitations

Approve and deny paths have been exercised, but the configured timeout and
park-on-no-response path has not yet been independently verified. Do not treat
timeout alone as a safety boundary for unattended destructive, production,
costly, or secret-bearing actions.

The maintainer's development repository has private historical commits. Its
pre-push hook blocks descendants of that history, but publication must still
start from a history-free `scripts/export-public.sh` snapshot.
