"""The convention files Nemo reads and wayworks writes.

These filenames are a contract between two separate repositories. Nemo's
preflight and runner read them; wayworks' `harness-init` creates them. Nothing
enforces that the two agree, because they are different repos with different
test suites — so a rename on either side breaks the other silently, across a
boundary neither repo's CI can see.

This module is the single place Nemo declares what it depends on. The contract
test (hermes/tests/seam_contract_test.py) asserts wayworks still creates these
exact names, when wayworks is checked out as a sibling. It is the one defence
the seam has.
"""

from __future__ import annotations

# The verify gate: a shell script whose zero exit means the tree is green.
# Read by preflight (must be committed) and by the runner's verify stage.
VERIFY_GATE = ".cc-verify"

# The dev-loop config: base branch, graders, retries. Read by preflight.
DEV_CONFIG = ".cc-dev.yaml"

# The deploy-loop config: deploy/watch/verify/rollback commands. Not read by
# Nemo yet (deploy is Phase 3), declared here so the contract covers it before
# it becomes load-bearing.
DEPLOY_CONFIG = ".cc-deploy.yaml"

# What preflight requires to exist and be committed before a loop can run.
GATE_FILES = (DEV_CONFIG, VERIFY_GATE)

# Everything the harness convention defines, for the contract test.
CONVENTION_FILES = (VERIFY_GATE, DEV_CONFIG, DEPLOY_CONFIG)
