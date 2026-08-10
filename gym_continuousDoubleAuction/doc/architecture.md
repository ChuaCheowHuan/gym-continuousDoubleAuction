# Architecture

How `gym-continuousDoubleAuction` is put together, layer by layer.

For what is *wrong* with it, see [known_issues.md](known_issues.md). For the history of how it got
here, see [changelog.md](changelog.md).

---

## 1. What it is

A multi-agent reinforcement learning environment (Gymnasium + Ray RLlib) that simulates a
**continuous double auction** — a limit order book exchange where *N* agents trade against each
other. There is no external market data: the price series is *generated* by the agents' own order
flow. Registered as `continuousDoubleAuction-v0` in [`__init__.py`](../__init__.py).

The repository is version 2 of a 2020 project, modernized for Gymnasium and RLlib 2.4+.

---

## 2. Layer map

Four layers, each in its own package:

| Layer | Package | Responsibility |
|---|---|---|
| Matching engine | [`envs/orderbook/`](../envs/orderbook/) | Price–time priority limit order book |
| Trader + accounting | [`envs/agent/`](../envs/agent/), [`envs/account/`](../envs/account/) | Order gating, cash escrow, position and NAV tracking |
| Environment | [`envs/continuousDoubleAuction_env.py`](../envs/continuousDoubleAuction_env.py), [`envs/exchg/`](../envs/exchg/) | Gym API, observation/action/reward/termination |
| Training | [`train/`](../train/) | Policies, league-based self-play callback, logging, plotting |

---

## 3. Matching engine — `envs/orderbook/`

Adapted from `dyn4mik3/OrderBook`. Classic price–time priority. Detailed semantics — including
modify-order behaviour — are in [matching_engine.md](matching_engine.md).

- [`order.py`](../envs/orderbook/order.py) — a single order; node in a doubly linked list, with
  `Decimal` price and quantity.
- [`orderlist.py`](../envs/orderbook/orderlist.py) — FIFO queue of orders at one price; head is
  highest priority.
- [`ordertree.py`](../envs/orderbook/ordertree.py) — `SortedDict` mapping price → `OrderList`, plus an `order_id → Order` map. One
  tree per side.
- [`orderbook.py`](../envs/orderbook/orderbook.py) — `process_order` dispatches market and limit
  orders; `process_limit_order` walks the opposite tree while the incoming order crosses, then
  rests the residual. Every fill appends a `transaction_record` to the tape with explicit
  `counter_party` / `init_party` dicts — that party attribution is the hook the accounting layer
  needs.

---

## 4. Trader and accounting — `envs/agent/`, `envs/account/`

Full walkthrough of the cash and position model is in [accounting.md](accounting.md).

- [`trader.py`](../envs/agent/trader.py) — `place_order` gates on `_order_approved`: NAV must be
  positive, and only the *opening* portion of an order (the part beyond flattening the current
  position) needs cash backing. It then routes to place / modify / cancel and calls
  `_process_trades`, which debits both sides of every fill.
- [`account.py`](../envs/account/account.py) — tracks `cash`, `cash_on_hold`, `position_val`,
  `net_position`, `VWAP`, `nav`, `max_nav`, plus the per-step reward counters. `process_acc`
  branches on long/short/neutral and on whether a fill increases, decreases, fully covers, or
  *flips* the position (`_covered_side_chg`).
- [`cash_processor.py`](../envs/account/cash_processor.py) — the escrow model: resting an order
  moves cash → `cash_on_hold` so agents cannot place unlimited orders; cancels and fills move it
  back.

All arithmetic is `Decimal`, so the simulation stays exactly zero-sum in NAV terms:
`total_sys_profit ≈ 0` and total NAV is conserved (checked in `exchg_helper.py`).

---

## 5. Environment — `envs/continuousDoubleAuction_env.py`

A thin shell over `envs/exchg/`, which is split across cooperative mixins:

```
continuousDoubleAuctionEnv(Exchg_Helper, MultiAgentEnv)
    └── Exchg_Helper
            └── State_Helper      ← consumes n_hist, calls super().__init__()
                    └── Action_Helper  ← initialises min_tick, mkt_size_mean_mul, ...
                            └── Reward_Helper
                                    └── Done_Helper
                                            └── Info_Helper
                                                    └── object
```

**MRO rule:** every `__init__` in the chain must call `super().__init__()`, and each class must
consume its own keyword arguments — nothing unrecognised may reach `object.__init__`, which raises
`TypeError`. This was the root cause of a real bug: `State_Helper.__init__` forwarding `n_hist=4`
down the chain aborted `Action_Helper.__init__` mid-body, surfacing as
`AttributeError: 'continuousDoubleAuctionEnv' object has no attribute 'min_tick'`.

(This mixin arrangement is a namespace-splitting device rather than genuine behavioural variance —
see [known_issues.md](known_issues.md) §2.7.)

### The step loop

`step()` does:

1. Snapshot the aggregated LOB — state at *t*.
2. `set_actions` — decode each agent's `Dict` action into an LOB-acceptable order.
3. `rand_exec_seq` — shuffle execution order so no agent has a structural queue advantage.
4. `do_actions` — feed orders through the book sequentially; collect trades and resting residuals.
5. `mark_to_mkt` — revalue every account at the last tape price.
6. Build next obs / rewards / terminateds / truncateds / infos, render, increment `t_step`.

**Key modelling assumption:** all traders share the same lag — nobody sees a new book snapshot
until every order in the step has executed.

### Observation

Per-frame layout is 42 floats (40 book features + 2 market scalars), stacked `n_hist` deep.
Default `n_hist = 4` → `(168,)`. Full specification, formulas, and history in
[observation_space.md](observation_space.md).

### Action

A flat `Dict` per agent: `category` (9), `size_mean`, `size_sigma`, `price` (10 depth levels),
`price_offset` (passive / join / aggressive). Full specification in
[action_space.md](action_space.md).

### Reward

NAV change with asymmetric loss aversion, minus penalties for order placement, trade count, and
drawdown from peak NAV, plus a bonus for passive fills. See [reward_function.md](reward_function.md).

Note this is deliberately *not* zero-sum: the README's "episode_reward = 0" description applies to
raw `NAV_chg`, which is now only the first term.

### Termination

[`done_helper.py`](../envs/exchg/done_helper.py): an agent is bankrupt at NAV ≤ 0 and added to
`done_set`; `terminated["__all__"]` fires when everyone is broke, `truncated["__all__"]` at
`max_step`.

---

## 6. Training — `train/`

The centrepiece is
[`train/callbk/league_based_self_play_callback.py`](../train/callbk/league_based_self_play_callback.py),
which replaces the original "copy the winner's weights onto the loser" self-play with league play
and champion snapshotting. Full description in [self_play_league.md](self_play_league.md).

Around it:

- [`policy_handler.py`](../train/policy/policy_handler.py) — PPO specs for the first *k* agents, a
  `RandomPolicy` for the rest.
- [`store_handler.py`](../train/storage/store_handler.py) — a Ray detached actor as a global metric
  store.
- [`log_handler.py`](../train/logger/log_handler.py) — gzipped JSON dumps.
- [`visualize/`](../visualize/) — replays episodes into price / size / NAV / reward plots.

---

## 7. Configuration

Passed as an `env_config` dict to `continuousDoubleAuctionEnv`:

| Key | Default | Meaning |
|---|---|---|
| `num_of_agents` | 5 | Number of traders |
| `init_cash` | 0 | Starting cash per trader |
| `tick_size` | 1 | Book tick size — **silently discarded after the first reset**, see [known_issues.md](known_issues.md) §3.6 |
| `tape_display_length` | 10 | Tape rows kept for display |
| `max_step` | 64 | Steps before truncation |
| `is_render` | `True` | Print book, tape, and accounts every step — turn off for training |
| `n_hist` | 4 | Observation history window |

---

## 8. Things worth knowing before touching it

- [`CDA_env_rand.py`](../CDA_env_rand.py) is stale: it calls the constructor with positional
  arguments and iterates `e.agents` as trader objects, but the current env takes a config dict and
  `agents` is a list of agent-id strings. [`random_agent.py`](../envs/agent/random_agent.py) is
  stale for the same reason — it still emits the old 5-tuple action instead of the current `Dict`.
- Per-agent `terminateds` are rebuilt as all-`False` each step; only `__all__` is ever set, so a
  single bankrupt agent keeps being stepped.
- `is_render` defaults to `True` and prints the full book, tape, and all accounts every step.
- A fair amount of commented-out dead code (old `step`, old action space, old `modify_order`) is
  left in place as inline history.
- The test suite is the best executable spec for the tricky parts — position flips, crossed books,
  volume sync, observation normalization. See [testing.md](testing.md).
