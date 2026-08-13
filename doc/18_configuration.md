# 18. Configuration

Every knob in the project, where it lives, and which ones are still hardcoded.

The `config/` folder at the repository root holds four JSON files that mirror the configuration
surfaces described here. **They are an inventory, not a loader** — nothing reads them at runtime.
Editing `config/env_config.json` does not change a run; it records what the keys are and what
their defaults mean. Configuration is applied in Python, via the `env_config` dict or
`TrainConfig`.

JSON has no comment syntax, so each file (and each group inside `tunable_constants.json`) carries
a `_source` key naming the module the values come from, and a `_description`. Loaders should skip
any key beginning with `_`.

---

## 1. The four surfaces

| File | Surface | Applied by |
|---|---|---|
| [`config/env_config.json`](../config/env_config.json) | Keys read from the `env_config` dict | `continuousDoubleAuctionEnv(config)` |
| [`config/train_config.json`](../config/train_config.json) | `TrainConfig` dataclass fields | `train.TrainConfig(...)` |
| [`config/cli_defaults.json`](../config/cli_defaults.json) | Command-line flags of the two entry points | `argparse` |
| [`config/tunable_constants.json`](../config/tunable_constants.json) | Constants with **no** config path | source edit only |

---

## 2. Environment config

Passed as an `env_config` dict to `continuousDoubleAuctionEnv`. See
[02_architecture.md](02_architecture.md) §2.6 for the table of the original seven keys and their
`TrainConfig` counterparts.

### 2.1 Order sizing

| Key | Default | Meaning |
|---|---|---|
| `min_size` | 1 | Smallest order size. Also the offset added to every sampled size, since 0 is not a valid order |
| `mkt_max_size` | 100 | Upper bound on market order size |
| `limit_size_multiple` | 10 | Limit orders may be this many times larger than market orders |

`limit_max_size` (= `mkt_max_size × limit_size_multiple`) and the two `*_size_mean_mul` values are
**derived**, not configured. `limit_size_multiple` was previously the single-letter attribute
`Action_Helper.N`.

### 2.2 Reward coefficients

| Key | Default | Meaning |
|---|---|---|
| `order_penalty` | 0.1 | Per order placed this step |
| `trade_penalty` | 0.05 | Per trade filled this step |
| `drawdown_penalty` | 0.2 | Per unit of NAV below the running peak |
| `passive_bonus` | 0.1 | Per passive (liquidity-providing) fill this step |
| `loss_multiplier` | 1.5 | Extra weight on negative NAV changes |

These were literals inside `Reward_Helper.set_reward` until they were promoted to config — the
parameters most worth sweeping were the least reachable in the project. The formula they feed is
documented in [07_reward_function.md](07_reward_function.md) §2, including why
`drawdown_penalty` in particular dominates the reward at the default scale.

### 2.3 How the keys reach their consumers

The env is assembled from cooperative mixins
([02_architecture.md](02_architecture.md) §2.2), so the new keys are forwarded along the MRO
rather than read directly by the classes that use them:

```
continuousDoubleAuctionEnv.__init__      reads config.get(...)
  └── Exchg_Helper.__init__              **kwargs
        └── State_Helper.__init__        **kwargs  (forwards, consumes n_hist)
              └── Action_Helper.__init__ consumes min_size, mkt_max_size,
                  │                      limit_size_multiple, tick_size
                  └── Reward_Helper.__init__ consumes the five coefficients
```

Every mixin consumes its own arguments and forwards the rest, so `kwargs` is empty by the time
the chain reaches `Done_Helper` / `Info_Helper`, which define no `__init__`. `State_Helper`
previously called `super().__init__()` with no arguments, which would have silently swallowed all
of these.

---
## 3. `tick_size` is half-live

`tick_size` sets the price grid the action space quotes on. It reaches
`Action_Helper.min_tick`, which is the only thing that constructs prices — `_set_price` builds
them as `anchor ± k × min_tick`.

**This used to be two independent values.** `Action_Helper.min_tick` was a hardcoded `1` that
actually drove prices, while the configured `tick_size` was passed to an `OrderBook` argument
that was stored and never read. Setting `tick_size` therefore had no effect anywhere. Both
defaults were 1, so wiring `min_tick` to the config key changed no behaviour at default config.

**The book's copy is still there, and still inert.** `OrderBook` accepts a `tick_size`, stores it,
and never reads it; there is no rounding or tick validation anywhere in the matching path. `reset()`
also still rebuilds the book as `OrderBook(1, ...)`, discarding whatever was passed. So the key
governs the action layer but not the book.

**The recommendation is to delete the book's copy, not to enforce it** — the action layer should
be the single definition. There is exactly one price producer in the system: every price reaching
`process_order` comes from `_set_price` via `place_order`, and it emits on-grid prices by
construction, so validation in the book would re-derive a guarantee the producer already provides.
Deletion is also nearly free — 9 of the 11 `OrderBook(...)` call sites already use the no-arg form,
and dropping the parameter makes the hardcoded `1` in `reset()` disappear rather than need a fix.

**This is deferred**: the `envs/orderbook/` package is off-limits to changes, and deleting the
parameter means editing `orderbook.py`. Tracked as S3-4 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md).

Enforcement in `OrderBook.process_order` would be the right call instead of deletion only if a
second price source appears that the action layer does not control — scripted or human agents,
replayed order flow, an external feed.

### 3.1 Float-grid caveat

`_set_price` performs **no** quantization, so a tick that is not binary-exact can in principle
produce a price whose `Decimal(str(price))` key sits off the grid, splitting one book level into
two price-map entries.

This is rarer than it sounds. Over all anchors 10–100, ticks {0.01, 0.05, 0.1, 0.2, 0.25, 0.3} and
ten levels either side, exactly one combination drifts: `10 − 9 × 0.3` → `7.300000000000001`.
Ticks of `1`, `0.5` and `0.25` are exact in binary and cannot be affected. Worth adding a
`Decimal` quantize step if non-integer ticks are ever used in earnest; it is not by itself a
reason to change anything.

---

## 4. Training config

`TrainConfig` ([`train.py`](../gym_continuousDoubleAuction/train/train.py)) groups the env keys it
forwards, the rollout/learner resources, the PPO hyperparameters, the league self-play settings
and the run/checkpoint settings. `TrainConfig.env_config` builds the dict handed to the env.

Network shape is configured through three fields — `fcnet_hiddens`, `fcnet_activation` and
`vf_share_layers` — which are threaded to `default_model_config` via `create_multi_agent_config`.
The latter two were previously hardcoded in `model_handler`, which split one network's
configuration across two files. `vf_share_layers` defaults to `False` deliberately: the learners
train against non-stationary league opponents, where sharing a trunk between policy and value
tends to destabilise the value estimate.

**Gap.** `initial_price_min` / `initial_price_max` are read by `reset()` but have no `TrainConfig`
field, so training runs cannot narrow the price-anchor range.

---

## 5. What is still hardcoded, and why

Recorded in [`config/tunable_constants.json`](../config/tunable_constants.json).

**Structural, not knobs.** `category: Discrete(9)` is hardwired to the `if`/`elif` mapping in
`_set_action_mkt_depth`, and `price_offset: Discrete(3)` to `offset_multiplier = price_offset - 1`;
changing either number without changing that logic does nothing. The `policy_` / `champion_`
module-ID prefixes are a naming contract `SelfPlayCallback` parses.

**Book depth is one concept, now stored in one place.** `K_ROWS` in `state_helper` is the single
definition; the action space's `price` component is `Discrete(K_ROWS)`, and `_set_price` reshapes
against `K_ROWS`. These were four independent literals that all happened to be 10 — two
`.reshape(4, 10)` calls, the `Discrete(10)`, and `K_ROWS` itself — so changing depth raised
`ValueError` or silently made high levels unreachable.

Depth is still **not** an `env_config` key. Promoting it requires `SNAPSHOT_DIM` to stop being a
module-level constant and become per-instance, since the observation space is built from it. That
is a real refactor and only worth doing if depth needs to vary per run; de-duplicating first makes
it a one-line edit either way.

**Fallback anchors.** The price used before any trade has printed is the literal `100.0`, written
twice — once in `Action_Helper.__init__` and once in the observation midpoint fallback in
`state_helper`. Both paths are dead in practice, since `reset()` overwrites `last_price` from
`initial_price_min` / `initial_price_max`, but the two literals should reference one constant so
they cannot drift apart.

**Entry-point paths.** The `visualize/` scripts take their input paths as function default
arguments with no CLI, so they are only overridable by importing and calling the function.
