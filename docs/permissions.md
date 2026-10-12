# Runtime permission guards

T007's project-owned guards live in `src/permissions/`. The framework Permission Engine cannot reliably intercept network calls made directly by provider adapters, so every external paid media integration must use `guarded_storyboard_call`.

## Before generation

1. Validate the storyboard against `schemas/storyboard.schema.json`.
2. Load unit prices recorded for the selected provider. `prepare_storyboard_quote` estimates all planned image, video and TTS work, including one retry, and writes the reservation to `runs/<run-id>/cost.json`. A missing price fails closed; the current project has no selected paid image or TTS provider, so those calls cannot proceed until a price is recorded.
3. Show that exact USD estimate at the human approval gate. The approval record must match the run ID, action names and `approved_estimate_usd` exactly.
4. Before each paid call, `guarded_storyboard_call` rechecks approval, quote, exact HTTPS host, run budget, project budget, and output path before dispatch. Parallel shots share the run-level quote. Output must be inside that run's own `runs/<run-id>/` directory.
5. After the provider reports usage, call `record_actual_cost`. When the run has no more paid work, call `settle_run_cost`; it releases unused estimate reserve from the project budget.

The provisional limits are USD 25 per run and USD 300 for the project. The quote reserves one retry for each planned item. `cost.json` records estimates, actuals, project totals and whether the reservation is settled. Malformed existing cost records stop new paid calls.

## Network and filesystem policies

- `require_allowed_host` accepts HTTPS only, default port 443 only, and exact normalized hostnames. Callers pass the configured RSS hosts, Tavily API host and the chosen provider API hosts. Article-page hosts stay outside the allowlist.
- `require_allowed_write_path` confines runtime writes to descendants of `runs/`. The `assets/cast/` subtree is available only when one-off cast setup explicitly opts in.
- The simple `guarded_paid_call` in `approval_guard.py` is retained for the Gate 0 approval-block check. Production paid media calls use the composite `guarded_storyboard_call` so they cannot skip the budget, host or output checks.

No paid image, video, or TTS request was made while implementing or testing these guards.