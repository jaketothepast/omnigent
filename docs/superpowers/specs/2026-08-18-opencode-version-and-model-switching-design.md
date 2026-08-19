# OpenCode: version-agnostic support + subagent model switching

Date: 2026-08-18
Status: approved

## Problem

Omnigent's opencode-native harness does not work against locally installed
OpenCode 1.18.9 for model selection, and its subagent dispatch cannot choose a
model for OpenCode workers at all. Concretely, the user cannot run
`kimi-k3` or `glm-5p2` (their `fireworks-ai` provider) through the harness.

## Findings (verified against a live `opencode serve` 1.18.9)

1. **The version gate is not the failure.** It accepts `>=1.17.7,<1.19.0`;
   1.18.9 passes. But the hard upper bound will break on 1.19/2.x.

2. **`list_models()` reads the wrong envelope key.**
   `opencode_native_client.py` reads `data["models"]`; 1.18.x returns
   `{"location": ..., "data": [...]}`. It silently yields `[]`.

3. **`GET /api/model` cannot see the user's models regardless.** The v2
   endpoint reported only the `opencode` and `local` providers (28 models).
   The `fireworks-ai` provider — holding `kimi-k3`, `kimi-k3-fast`,
   `glm-5p2`, `glm-5p2-fast` — is absent. The v1 `GET /provider` endpoint
   returns `{all: [...192 providers...], connected: [...], default: {...}}`
   and does include it.

4. **OpenCode is absent from the subagent model catalog.**
   `model_catalog._PROVIDER_RESOLUTION_HARNESS` has no opencode entry, so
   `resolve_model_provider(spec, "opencode-native")` returns
   `kind="none", detail="harness 'opencode-native' has no model-provider
   resolution"`. `sys_list_models` therefore reports no models for OpenCode
   workers. This is the model-switching gap.

### What already works (do not rebuild)

- `opencode models --refresh` returns all 31 of the user's models, including
  K3 and GLM 5.2, and `list_opencode_cli_model_options` parses them
  correctly — multi-slash ids such as
  `fireworks-ai/accounts/fireworks/models/kimi-k3` split correctly on the
  first `/`.
- `_split_model` in `opencode_http_transport.py` produces the right
  `{providerID, modelID}` for those ids.
- `validate_model_override` accepts them; `model_family_mismatch` correctly
  treats opencode as multi-vendor and rejects nothing.
- `opencode_native_executor.py` already pins `model_override` on every
  prompt, so a selected model governs from turn one.

## Design

### 1. Version gate: floor-only, warn above validated

Files: `omnigent/opencode_native_client.py`,
`omnigent/opencode_native_app_server.py`.

Remove `OPENCODE_MAX_VERSION_EXCLUSIVE`. Add advisory
`OPENCODE_MAX_VALIDATED_VERSION = "1.18"`. `check_opencode_version` becomes:

| Input | Behaviour |
|---|---|
| `< 1.17.7` | raise `OpenCodeVersionError` (API genuinely differs) |
| `>= 1.17.7`, `<= validated` | proceed silently |
| above validated | log one warning, proceed |
| unparsable | log one warning, proceed |

`OMNIGENT_OPENCODE_SKIP_VERSION_CHECK` is retained.

### 2. Model listing fallback: v1 `/provider`, filtered to `connected`

File: `omnigent/opencode_native_client.py`.

`list_models()` becomes: query `GET /provider`; keep providers whose id is in
`connected`; emit one row per model as `{provider}/{model}`. Fall back to
`GET /api/model` accepting **both** `data` and `models` envelope keys, so old
and new servers both work.

Rows are normalized to the shape `list_opencode_cli_model_options` returns
(`id`, `model`, `providerID`, `name`, `displayName`, `isDefault`) because
`runner/app.py` returns the CLI and HTTP results interchangeably.

### 3. Wire OpenCode into the subagent model catalog

File: `omnigent/model_catalog.py`.

Mirror the existing cursor precedent:

- add `_OPENCODE_HARNESSES = {"opencode", "opencode-native", "native-opencode"}`
- short-circuit it in `_resolve_model_provider_unsafe` to a CLI-catalog
  provider descriptor (OpenCode owns a multi-provider catalog and has no
  Databricks resolution path)
- add `_fetch_opencode_cli_listing`, alongside `_fetch_cursor_cli_listing`,
  sourced from `list_opencode_cli_model_options`

This inherits the existing TTL cache and family-token logic.

**Found during self-review:** `_listing_for_provider` caught
`click.ClickException / httpx.HTTPError / OSError / ValueError /
subprocess.SubprocessError`. The Cursor lister signals failure as
`ValueError`, but the OpenCode lister raises `RuntimeError` subclasses
(`OpenCodeCliNotFoundError`, plus plain `RuntimeError` for a non-zero exit),
so a missing or logged-out OpenCode CLI escaped the handler instead of
degrading to an empty listing. `RuntimeError` was added to the caught tuple,
with a regression test asserting the failure degrades and is not cached.

Outcome: `sys_list_models` reports the real 31 models for OpenCode workers,
and a subagent can be dispatched with
`model: "fireworks-ai/accounts/fireworks/models/kimi-k3"`.

## Testing

- Unit tests per change, including a `< 1.17.7` rejection, an above-validated
  warn-and-proceed, the `data`/`models` envelope compatibility pair, and the
  `connected` filter.
- The existing 68 opencode unit tests stay green.
- Live verification against the user's real `opencode serve` 1.18.9: K3 and
  GLM 5.2 must appear in both the harness listing and `sys_list_models`.

## Verification performed

Against the user's real `opencode serve` 1.18.9:

- `list_models()` returns 31 models across `fireworks-ai` / `opencode` /
  `local`, matching `opencode models` exactly. The `/api/model` fallback
  returns 28 and omits `fireworks-ai`, confirming why it is the fallback.
- `list_models_for_worker(spec, "opencode-native")` returns the same 31 with
  `source="cli", verified=True`.
- A live turn pinned to `fireworks-ai/accounts/fireworks/models/kimi-k3` and
  another to `.../routers/glm-5p2-fast` were each served by exactly the
  requested model (assistant message `providerID`/`modelID` matched).
- `normalize_model_for_provider` leaves the multi-slash ids untouched under
  the new `subscription` kind, and `harness_supports_model_override` is true
  for `opencode-native`.
- `tests/e2e/test_opencode_native_wire_contract_e2e.py` passes against the
  real binary.

## Scope

Out of scope: any upstream pull request, changes to other harnesses, and web
UI changes. Fix 3 touches shared `model_catalog.py`, but is purely additive
and follows the cursor precedent. Polly's default agent roster is deliberately
unchanged; cross-model routing uses per-dispatch selection or user-authored
worker pins.
