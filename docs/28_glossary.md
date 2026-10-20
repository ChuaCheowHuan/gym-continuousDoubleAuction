# 28. Glossary

The terms the other documents use, in one place. Each entry says what the word means **in this
repository** and links to the document that owns it. Where the code has a name for the thing, it
is given in `code`.

---

## Market and matching

| Term | Meaning here | Owner |
|---|---|---|
| **Continuous double auction (CDA)** | Buyers and sellers quote at any time; an incoming order that crosses the opposite side trades at once against resting orders | [01](01_overview.md) §1.2 |
| **Limit order book (LOB)** | The resting orders, bids and asks, sorted by price then arrival time. `OrderBook` | [03](03_matching_engine.md) |
| **Price-time priority** | The better price fills first; at one price, the earlier order fills first (`matching_rule: fifo`) | [03](03_matching_engine.md) |
| **Pro-rata** | The alternative `matching_rule`: a price level's fill is split in proportion to order size, with the rounding remainder handed out in time order | [06](06_action_space.md) §8 |
| **Sequential / batch clearing** | `step_clearing`. Sequential: each order matches on arrival, in the step's shuffled order. Batch: the step's new orders clear together at one uniform price | [06](06_action_space.md) §8 |
| **Market / limit / modify / cancel** | The four order types. Modify re-prices one of the trader's own resting orders; cancel withdraws one, or all on that side | [06](06_action_space.md) |
| **Touch, best bid, best ask** | The best price on each side of the book | [03](03_matching_engine.md) |
| **Mid** | The midpoint of the best bid and best ask | [05](05_observation_space.md) |
| **Spread** | Best ask minus best bid, measured in ticks in the observation | [05](05_observation_space.md) |
| **Tick, tick grid** | `tick_size`, the smallest price step. Every quoted price is a multiple of it | [06](06_action_space.md) |
| **Tape** | The record of every fill, with both parties, price, size and time | [03](03_matching_engine.md) |
| **Self-match prevention** | Before an order reaches the book, the trader's own opposite orders it would trade with are cancelled | [04](04_accounting.md) |
| **Maker / taker** | The resting order is the maker, the incoming one the taker. Each can have its own fee, `maker_fee_bps` / `taker_fee_bps` | [04](04_accounting.md) §9 |

## Accounts and risk

| Term | Meaning here | Owner |
|---|---|---|
| **Cash, cash on hold (escrow)** | `cash` is free money. `cash_on_hold` is set aside to back the trader's resting orders and is released when an order fills or is cancelled | [04](04_accounting.md) |
| **Position, net position** | Contracts held: positive is long, negative is short. `net_position` | [04](04_accounting.md) |
| **Cost basis, VWAP, entry VWAP** | `cost_basis` is the exact sum of trade values that built the position. `VWAP` is derived from it for display, and can go negative after a partial close. `entry_vwap` is the average price actually paid | [04](04_accounting.md) |
| **Mark, mark price, mark to market** | The price every account is valued at after a step. By default the mid of a two-sided book, else the last trade (`mark_price_source`) | [04](04_accounting.md), [02](02_architecture.md) §2.5 |
| **NAV** | Net asset value: `cash + cash_on_hold + position_val` | [04](04_accounting.md) |
| **NAV conservation** | Money is neither created nor lost: `sum(NAV) + fees_collected == starting cash`, checked at every episode end | [04](04_accounting.md), [11](11_logging_and_observability.md) |
| **Realised / unrealised P&L** | Profit banked by closing lots, and profit still open at the mark | [04](04_accounting.md) |
| **Cash check** | `Trader._order_approved`: an order is refused unless NAV is positive and the *opening* part of the order is backed by cash. Closing a position needs no cash | [04](04_accounting.md) |
| **Maintenance margin** | A trader whose NAV falls to `maintenance_margin` × position value is liquidated | [04](04_accounting.md) §8 |
| **Liquidation, bankruptcy price** | The forced close of a trader in breach: in the book, no worse than the price at which its NAV would reach zero | [04](04_accounting.md) §8 |
| **ADL (auto-deleveraging)** | What the book cannot absorb is transferred at the mark to traders on the other side. `market_adl` closes at once; `gradual_adl` over `liquidation_horizon` steps | [04](04_accounting.md) §8 |
| **Bankrupt, done** | NAV at or below zero. The agent is terminated and its orders are pulled | [04](04_accounting.md), [02](02_architecture.md) |

## The learning problem

| Term | Meaning here | Owner |
|---|---|---|
| **Agent, trader** | One participant. `agent_<i>` is the RL name; `Trader` the object holding its account | [02](02_architecture.md) |
| **Step, episode, horizon** | One step: every agent acts once and the book clears. An episode is truncated at `max_step`, or at a horizon drawn per episode when `episode_length_mode` is `random` | [02](02_architecture.md) §2.5 |
| **Observation** | 233 floats in `grid` mode, 305 in `levels` mode: four stacked book snapshots plus the agent's 41-float private block | [05](05_observation_space.md) |
| **Grid / levels mode** | `book_mode`. Grid: book sizes on a fixed window of tick offsets around the reference price. Levels: the top levels' prices and sizes | [05](05_observation_space.md) |
| **Reference price** | The mid snapped to the tick: the origin of the grid, and the price the action's price codes are counted from | [05](05_observation_space.md), [06](06_action_space.md) |
| **Private block** | The agent's own state in the observation: cash, position, resting orders, the action mask, time left | [05](05_observation_space.md) §1.0 |
| **Action heads** | The five parts of the `Dict` action: `category`, `size`, `price`, `price_offset`, `order_slot` | [06](06_action_space.md) |
| **Ghost level** | A price used when the requested book level is empty, stepped off the last traded price | [06](06_action_space.md) |
| **Pass** | Category 0: do nothing this step. Always allowed | [06](06_action_space.md) |
| **Action mask** | Marks the categories an agent cannot take this step (nothing to cancel, cannot afford the minimum order), so the policy never samples them | [06](06_action_space.md) §7 |
| **Rejected / unmatched (dead action)** | Rejected: the cash check refused the order. Unmatched: a modify or cancel with nothing resting to act on | [06](06_action_space.md), [11](11_logging_and_observability.md) |
| **Reward terms** | Six signed terms, in units of starting capital: `nav_term`, `order_penalty`, `trade_penalty`, `drawdown_penalty`, `passive_bonus`, `dead_action_penalty` | [07](07_reward_function.md) |
| **Drawdown** | Distance below the agent's peak NAV. The reward charges its *change*, not its level | [07](07_reward_function.md) |
| **Passive fill** | A fill in which the agent's order was the resting one | [07](07_reward_function.md) |
| **Mark-out** | How a fill looks `h` steps later, measured against the mid then | [11](11_logging_and_observability.md) |

## Training

| Term | Meaning here | Owner |
|---|---|---|
| **RLModule, module** | One policy network. `policy_<i>` are trainable or random baselines; `champion_<n>` are frozen snapshots | [08](08_self_play_league.md) |
| **League self-play** | Trainable policies play against a pool of opponents: random baselines and frozen past champions | [08](08_self_play_league.md) |
| **Champion, promotion** | A trainable policy whose return clears the league mean by `std_dev_multiplier` standard deviations is copied, frozen, into the pool | [08](08_self_play_league.md) |
| **Matchmaking** | The mapping function that assigns each non-trainable agent a module from the pool, weighted by `champion_weight` and `original_opponent_weight` | [08](08_self_play_league.md) |
| **Idle module** | A module drawn into no episode this iteration. It is left out of the league statistics | [08](08_self_play_league.md) |
| **Env runner, learner** | RLlib's sampling processes (`num_env_runners`) and update processes (`num_learners`) | [09](09_distributed_training.md) |
| **Iteration** | One `algo.train()` call: sample a batch, run PPO's update epochs, check the league | [09](09_distributed_training.md), [26](26_runbook.md) |
| **Encoder** | The network that turns the observation into features for the policy and value heads. Five are selectable by `encoder_type` | [18](18_configuration.md) §5.4 |
| **JEPA** | Joint-embedding predictive architecture: a self-supervised objective that predicts masked observation latents from visible ones | [22](22_jepa_integration.md), [23](23_probe_harness.md) Part 2 |
| **Probe** | A linear model scoring an encoder's features on future market quantities, with no reward involved | [23](23_probe_harness.md) |
| **CBP (Continual Backprop)** | Re-initialising low-utility hidden units during training to keep the network plastic | [25](25_continual_backprop.md) |
| **Episode record** | The Parquet file with one row per (episode, step, agent) | [11](11_logging_and_observability.md) |

## Project vocabulary

| Term | Meaning here | Owner |
|---|---|---|
| **Finding, S1–S4** | A confirmed defect or gap, ranked from blocking (S1) to minor (S4). Open ones are in 15; fixed ones move, under the same ID, to 29 | [15](15_findings_and_recommendations.md), [29](29_fixed_issues.md) |
| **R-n** | An item from the 2026-10-07 review. The fixed ones are in 29; the ones documented or guarded instead are open decisions in 15 | [15](15_findings_and_recommendations.md), [29](29_fixed_issues.md) |
| **Layout version** | The observation and action layout stamped beside a checkpoint, so weights are never read against a different layout | [05](05_observation_space.md) |
