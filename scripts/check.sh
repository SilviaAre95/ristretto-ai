#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

python_bin="python3"
if [ -x "$repo/.venv/bin/python" ]; then
  python_bin="$repo/.venv/bin/python"
fi

"$python_bin" -m unittest hermes/tests/ristretto_config_test.py
bash -n scripts/*.sh hermes/tests/*.sh hermes/skills/loop-runner/scripts/*.sh
bash hermes/tests/install.test.sh
bash hermes/tests/reap.test.sh
bash hermes/tests/ris-stop.test.sh
bash hermes/tests/run-loop.test.sh
bash hermes/tests/morning-brief-precheck.test.sh
bash hermes/tests/push-guard.test.sh

"$python_bin" -m ristretto.cli --config "$repo/ristretto.yaml" validate
"$python_bin" -c 'import json, pathlib, yaml; json.load(open("hermes/cron/jobs.example.json")); [json.load(open(path)) for path in pathlib.Path("slack").glob("*.json")]; [yaml.safe_load(path.read_text()) for root in (pathlib.Path("hermes"), pathlib.Path(".github/workflows")) for pattern in ("*.yaml", "*.yml") for path in root.glob(pattern)]; print("config parse: ok")'
git diff --check
git diff --cached --check
bash scripts/scan-secrets.sh

echo "check: ok"
