#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

python_bin="python3"
if [ -x "$repo/.venv/bin/python" ]; then
  python_bin="$repo/.venv/bin/python"
fi

# The suite reads the shipped config, never the developer's own. Several tests
# reach `load_config()` with no path through `start_flow`, which resolves
# $XDG_CONFIG_HOME/cuzam/config.yaml when it exists — so their result depended
# on the personal config file of whoever ran them, and they passed on CI (which
# has none) while failing locally on a config CI never sees. That is why this
# file's instructions used to say to run the suite a second time with
# XDG_CONFIG_HOME pointed at an empty directory "which is what CI sees": the
# ritual existed because the suite was not hermetic. CUZAM_CONFIG wins over XDG
# discovery, so setting it here makes local and CI the same run.
#
# Tests that mean to exercise layering pass an explicit path and are unaffected.
#
# Discovered, not listed. A hand-maintained list means a new test file runs
# green locally and never runs here at all, which is worse than no test:
# cuzam_approvals_test.py sat uncollected until its absence was noticed
# by the suite total not moving.
# Dashboard tests skip their route cases when the [dash] extra is absent.
export CUZAM_CONFIG="$repo/cuzam.yaml"
PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}" \
  "$python_bin" -m unittest discover -s hermes/tests -p '*_test.py' -t hermes/tests
"$python_bin" -m unittest discover -s tests
bash -n scripts/*.sh hermes/tests/*.sh hermes/skills/loop-runner/scripts/*.sh
bash hermes/tests/install.test.sh
bash hermes/tests/reap.test.sh
bash hermes/tests/zam-stop.test.sh
bash hermes/tests/run-loop.test.sh
bash hermes/tests/flow-guard.test.sh
bash hermes/tests/morning-brief-precheck.test.sh
bash hermes/tests/push-guard.test.sh
bash hermes/tests/trim-logs.test.sh
bash hermes/tests/link-loop-runner.test.sh
bash hermes/tests/template-drift.test.sh
bash hermes/tests/live-runs.test.sh
bash hermes/tests/migrate-cuzam.test.sh

"$python_bin" -m cuzam.cli --config "$repo/cuzam.yaml" validate
"$python_bin" -c 'import json, pathlib, yaml; json.load(open("hermes/cron/jobs.example.json")); [json.load(open(path)) for path in pathlib.Path("slack").glob("*.json")]; [yaml.safe_load(path.read_text()) for root in (pathlib.Path("hermes"), pathlib.Path(".github/workflows")) for pattern in ("*.yaml", "*.yml") for path in root.glob(pattern)]; print("config parse: ok")'
git diff --check
git diff --cached --check
bash scripts/scan-secrets.sh

echo "check: ok"
