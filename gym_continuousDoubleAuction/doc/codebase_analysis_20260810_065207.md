# Codebase Analysis (generated 2026-08-10 06:52:07)

## What it is

A multi-agent reinforcement learning environment (Gymnasium + Ray RLlib) that simulates a
**continuous double auction** — a limit order book exchange where N agents trade against each
other. There's no external market data: the price series is *generated* by the agents' own order
flow. Registered as `continuousDoubleAuction-v0` in
[`__init__.py`](../__init__.py).

The repo is version 2 of a 2020 project, modernized for Gymnasium/RLlib 2.4+ (see
[`doc/change.md`](change.md)).

## Architecture

Four layers, each in its own package:

### 1. Matching engine — `envs/orderbook/`

Adapted from `dyn4mik3/OrderBook`. Classic price–time priority:

- [`order.py`](../envs/orderbook/order.py) — a single order, node in a doubly linked list,
  `Decimal` price/quantity.
- [`orderlist.py`](../envs/orderbook/orderlist.py) — FIFO queue of orders at one price; head =
  highest priority.
- [`ordertree.py`](../envs/orderbook/ordertree.py) — `SortedDict` mapping price → OrderList, plus
  an `order_id → Order` map. One tree per side.
- [`orderbook.py`](../envs/orderbook/orderbook.py) — `process_order` handles market/limit;
  `process_limit_order` walks the opposite tree while it crosses (line 161), then rests the
  residual. Every fill appends a `transaction_record` to the tape with explicit `counter_party` /
  `init_party` dicts — that party attribution is the hook the accounting layer needs.
  `modify_order` (line 202) keeps queue priority only when price is unchanged and quantity
  shrinks; otherwise it pulls and re-processes the order.

### 2. Trader + accounting — `envs/agent/trader.py`, `envs/account/`

- `Trader.place_order` gates on `_order_approved` (trader.py:68): NAV must be positive, and only
  the *opening* portion of an order (the part beyond flattening the current position) needs cash.
  It then routes to place/modify/cancel and calls `_process_trades`, which debits both sides of
  every fill.
- [`account.py`](../envs/account/account.py) tracks `cash`, `cash_on_hold`, `position_val`,
  `net_position`, `VWAP`, `nav`, `max_nav`. `process_acc` branches on long/short/neutral and on
  whether the fill increases, decreases, fully covers, or *flips* the position
  (`_covered_side_chg`).
- [`cash_processor.py`](../envs/account/cash_processor.py) implements the escrow model: resting an
  order moves cash → `cash_on_hold` so agents can't place unlimited orders; cancels and fills move
  it back.
- All arithmetic is `Decimal`, so the simulation stays exactly zero-sum: `total_sys_profit ≈ 0`
  and total NAV is conserved (`exchg_helper.py:229`).

### 3. Environment — `envs/continuousDoubleAuction_env.py`

Thin shell over `envs/exchg/`, which is split by mixin:
`Exchg_Helper(State_Helper, Action_Helper, Reward_Helper, Done_Helper, Info_Helper)`.

A `step` (continuousDoubleAuction_env.py:210) does:

1. Snapshot the aggregated LOB (state at *t*).
2. `set_actions` — decode each agent's Dict action into an LOB-acceptable order.
3. `rand_exec_seq` — shuffle execution order so no agent has a structural queue advantage.
4. `do_actions` — feed orders through the book sequentially; collect trades and resting
   residuals.
5. `mark_to_mkt` — revalue every account at the last tape price.
6. Build next obs / rewards / terminateds / truncateds / infos, render, increment `t_step`.

The key modelling assumption: all traders share the same lag — nobody sees a new book snapshot
until every order in the step has executed.

**Observation** (`envs/exchg/state_helper.py`): top 10 levels each side →
`[bid_prices, bid_sizes, ask_prices, ask_sizes]`, 40 floats. Asks are stored negated (sign encodes
side). Two transforms:

- Prices normalized to distance from the L1 midpoint `M`: bids `(M - P)/M ≥ 0`, asks
  `-((|P| - M)/M) ≤ 0`. When the book is one-sided or empty it falls back to `last_price`.
- Sizes scaled `±√volume` to tame variance.

Then `n_hist` (default 4) snapshots are stacked into a `(160,)` vector via a `deque`, giving
agents temporal flow rather than a single frame. The *unnormalized* book is kept in parallel as
`agg_LOB_raw` — that's what actions resolve prices against.

**Action space** (`envs/exchg/action_helper.py:37`) is a flat `Dict` per agent:

- `category` Discrete(9): none, or {buy,sell} × {market, limit, modify, cancel}
- `size_mean` / `size_sigma`: parameters of a normal draw for order size, scaled differently for
  market vs. limit
- `price` Discrete(10): which depth level to reference
- `price_offset` Discrete(3): passive (−1 tick) / join / aggressive (+1 tick)

`_set_price` (action_helper.py:228) looks up the raw price at that level; if the level is empty it
synthesizes a "ghost" price relative to `last_price`, so the mapping is deterministic and always
defined.

**Reward** (`envs/exchg/reward_helper.py`): NAV change with asymmetric loss aversion (×1.5 on
losses), minus penalties for placing orders, for trade count, and for drawdown from peak NAV, plus
a bonus for passive fills (spread capture). Note this is deliberately *not* zero-sum any more — the
README's "episode_reward = 0" description applies to raw `NAV_chg`, which is now only the first
term.

**Termination** (`envs/exchg/done_helper.py`): an agent is bankrupt at NAV ≤ 0 and added to
`done_set`; `terminated["__all__"]` when everyone is broke, `truncated["__all__"]` at `max_step`.

### 4. Training — `train/`

The interesting piece is
[`train/callbk/league_based_self_play_callback.py`](../train/callbk/league_based_self_play_callback.py).
Instead of the original "copy the winner's weights onto the loser" self-play, it does league play
with champion snapshotting:

- `on_train_result` computes league mean/std of policy returns; if the best trainable policy
  exceeds `mean + k·std` (and a cooldown has passed), its module is frozen and cloned into the
  opponent pool as `champion_N`.
- A rolling window (`max_champions`) drops the oldest.
- `get_mapping_fn` (line 514) assigns non-trainable agent slots by weighted random draw over
  {original random policies, champions}, seeded from the episode id so the mapping is
  deterministic per episode.
- `on_episode_end` also pickles per-step data and runs a NAV conservation check (total NAV should
  equal total initial cash).

Around that: [`policy_handler.py`](../train/policy/policy_handler.py) (PPO specs for the first *k*
agents, a `RandomPolicy` for the rest),
[`store_handler.py`](../train/storage/store_handler.py) (a Ray detached actor as global metric
store), [`log_handler.py`](../train/logger/log_handler.py) (gzipped JSON dumps), and
[`visualize/`](../visualize/) for replaying episodes into price/size/NAV/reward plots.

## Things worth knowing before touching it

- [`CDA_env_rand.py`](../CDA_env_rand.py) is stale: it calls the constructor with positional args
  and iterates `e.agents` as trader objects, but the current env takes a config dict and `agents`
  is now a list of agent-id strings. Same for
  [`random_agent.py`](../envs/agent/random_agent.py), which still emits the old 5-tuple action
  instead of the current Dict.
- Per-agent `terminateds` are rebuilt as all-`False` each step (`done_helper.py:32`); only
  `__all__` is ever set, so a single bankrupt agent keeps being stepped.
- `is_render` defaults to `True` and `_render` prints the full book, tape, and all accounts every
  step — turn it off for training.
- There's a fair amount of commented-out dead code (old `step`, old action space, old
  `modify_order`) left in place as history.
- The test suite (`test/`, 13 `unittest` cases) is the best spec for the tricky parts: position
  flips, crossed books, volume sync between tree and list, and observation normalization.
