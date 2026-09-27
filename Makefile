.PHONY: setup install install-runtime install-hermes install-push-guard install-dash-service migrate-cuzam update test check public-check doctor

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

# One-time, for the Ristretto -> Cuzam rename of everything outside the
# checkout: the state home, the user config, the Hermes plugins and scripts,
# the worker profile, the doorbell cron job and the launchd label. Idempotent,
# and it refuses while a run is live. See the upgrade notes in CHANGELOG.md.
#
# Named after the script rather than `migrate`, because `cuzam migrate` is a
# different command that shares only the verb: that one reports and adopts
# config-layer drift between the shipped configuration and the user's copy, and
# it is the one an upgrader would find first. The rename is the one they
# actually have to run, so the two must not be guessable for each other.
migrate-cuzam:
	bash scripts/migrate-cuzam.sh

update:
	bash scripts/update.sh

# CUZAM_CONFIG for the same reason scripts/check.sh sets it: several tests
# reach load_config() with no path and would otherwise read the developer's own
# configuration.
test: export CUZAM_CONFIG=$(CURDIR)/cuzam.yaml
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
