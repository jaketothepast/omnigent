# OpenCode: model selection

How to pick which model an OpenCode worker runs, at three levels.

## Model ids

An OpenCode model id is always `provider/model`, exactly as
`opencode models` prints it. The provider prefix is what selects the
credential, so it is required — and the model half may itself contain
slashes:

```
$ opencode models
fireworks-ai/accounts/fireworks/models/kimi-k3
fireworks-ai/accounts/fireworks/routers/kimi-k3-fast
fireworks-ai/accounts/fireworks/routers/glm-5p2-fast
local/qwen-3.6
```

Only providers you have credentials for appear. Add one with
`opencode auth login`.

## 1. Per dispatch — `args.model`

An orchestrator picks the model when it dispatches, via `args.model` on
`sys_session_send`. Call `sys_list_models` first to see what a worker can
actually run; it reports the live catalog above for OpenCode workers.

```
sys_list_models              -> {"opencode": {"source": "cli", "models": [...]}}
sys_session_send  args.model = "fireworks-ai/accounts/fireworks/models/kimi-k3"
```

This is the most flexible option: one OpenCode worker, any model per task.
An invalid id format fails at the dispatch gate; a well-formed model that the
provider cannot route returns OpenCode's error from the worker.

## 2. Per agent — `executor.model`

To pin a model as an agent's default, set `executor.model` in its
`config.yaml`:

```yaml
spec_version: 1
name: opencode_k3
executor:
  type: omnigent
  model: fireworks-ai/accounts/fireworks/models/kimi-k3
  config:
    harness: opencode-native
```

The pin governs from turn one — OpenCode's create-session body takes no
model, so Omnigent applies it to every prompt it injects. A dispatch's
`args.model` still overrides it.

For cross-model review, define separate workers with this field or dispatch
different models to an existing OpenCode worker. Keep the orchestrator's
declared worker roster and prompt in sync when adding a worker.

## 3. Interactively

In an OpenCode session, `/model` switches the model as usual. OpenCode
persists the last-used model on the session, so the switch sticks for later
turns.

## Which OpenCode versions work

Omnigent requires OpenCode `>= 1.17.7`; earlier releases lack the `/session`
and `/provider` endpoints it calls, and are refused with a clear message.
There is no upper bound — a release newer than the line Omnigent has
validated logs one warning and runs. `OMNIGENT_OPENCODE_SKIP_VERSION_CHECK=1`
silences the check entirely.

## Troubleshooting

**A worker lists no models.** `sys_list_models` reports the reason in its
`note`. The catalog comes from `opencode models --refresh`, so check that
`opencode` is on `PATH` and `opencode auth login` has been run for the
provider you want. Failures are not cached — fix the cause and the next call
picks it up (otherwise the listing caches for 5 minutes).

**A model is missing from the list.** Only `connected` providers are listed.
`opencode auth login` for that provider, then retry.
