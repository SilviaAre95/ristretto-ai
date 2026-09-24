.PHONY: setup install install-runtime install-hermes install-push-guard install-dash-service migrate update test check public-check doctor

setup:
	bash scripts/setup-dev.sh

install:
	bash scripts/install.sh

install-runtime:
	bash scripts/install-runtime.sh

install-hermes: install
	bash scripts/install-hermes.sh

install-push-guard:
	bash scripts/install-private-push-guard.sh

# One-time, for the 0.2.0 -> Cuzam rename. Idempotent; see CHANGELOG.md.
migrate:
	bash scripts/migrate-cuzam.sh

update:
	bash scripts/update.sh

test:
	.venv/bin/python -m unittest hermes/tests/cuzam_config_test.py
	.venv/bin/python -m unittest discover -s tests
	bash hermes/tests/install.test.sh
	bash hermes/tests/reap.test.sh
	bash hermes/tests/zam-stop.test.sh
	bash hermes/tests/run-loop.test.sh
	bash hermes/tests/morning-brief-precheck.test.sh
	bash hermes/tests/push-guard.test.sh
	bash hermes/tests/link-loop-runner.test.sh
	bash hermes/tests/template-drift.test.sh
	bash hermes/tests/live-runs.test.sh
	bash hermes/tests/migrate-cuzam.test.sh

check:
	bash scripts/check.sh

public-check:
	bash scripts/check-public.sh

doctor:
	hermes doctor
	hermes gateway status
	bash scripts/template-drift.sh

install-dash-service:
	bash scripts/install-dash-service.sh install
