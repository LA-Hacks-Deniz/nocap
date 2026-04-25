# Owner: DEVIN — Phase 1 task T1.16
#
# Top-level Makefile for the No Cap repo. Currently hosts the Phase 1
# smoke test against the Adam fixtures; future targets (Phase 2/3) get
# added alongside.
#
# Requirements for `make smoke-adam`:
#   * `uv` on PATH (the repo standardizes on uv for Python deps)
#   * `GOOGLE_API_KEY` exported in the environment (live Gemma call —
#     the smoke test deliberately runs against the real API so that
#     regressions in Spec / Plan / Critic prompt formatting don't slip
#     through). Without the key the orchestrator will crash on the
#     first `spec.extract_claim` call and `make smoke-adam` will fail
#     loudly.
#
# The CLI exits 0 on verdict=pass, 1 on anomaly. `smoke-adam` therefore
# inverts the buggy invocation's exit code with `!` so make sees
# success when the CLI correctly reports anomaly.

.PHONY: smoke-adam

smoke-adam:
	@echo "=== adam_clean (expect: pass / exit 0) ==="
	@cd nocap-council && uv run nocap verify-impl \
	    1412.6980 ../benchmark/implementations/adam_clean.py
	@echo
	@echo "=== adam_buggy (expect: anomaly / exit 1) ==="
	@cd nocap-council && ! uv run nocap verify-impl \
	    1412.6980 ../benchmark/implementations/adam_buggy.py
	@echo
	@echo "✓ smoke-adam passed (clean=pass, buggy=anomaly)"
