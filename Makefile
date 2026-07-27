.PHONY: setup install install-hermes install-push-guard test check public-check doctor

setup:
	bash scripts/setup-dev.sh

install:
	bash scripts/install.sh

install-hermes: install
	bash scripts/install-hermes.sh

install-push-guard:
	bash scripts/install-private-push-guard.sh

test:
	.venv/bin/python -m unittest hermes/tests/ristretto_config_test.py
	.venv/bin/python -m unittest discover -s tests
	bash hermes/tests/install.test.sh
	bash hermes/tests/reap.test.sh
	bash hermes/tests/ris-stop.test.sh
	bash hermes/tests/run-loop.test.sh
	bash hermes/tests/morning-brief-precheck.test.sh
	bash hermes/tests/push-guard.test.sh

check:
	bash scripts/check.sh

public-check:
	bash scripts/check-public.sh

doctor:
	hermes doctor
	hermes gateway status
