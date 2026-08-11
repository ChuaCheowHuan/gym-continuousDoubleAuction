# Known Issues

A critique of `gym-continuousDoubleAuction` across intent, concept, design, and implementation,
consolidating what were previously three separate analysis documents (whole-repo problems, the
observation-space review, and the logging audit — the last of which now lives in
[logging.md](logging.md)).

[architecture.md](architecture.md) describes how the system works. This document describes what is
wrong with it.

Findings are ordered by cost, not by layer. File and line references were verified against the tree
at commit `115731e` on branch `relative_orderbook`.

---

## 1. Conceptual problems — the deepest ones

### 1.1 Agents cannot see their own state, but the reward depends entirely on it

**The single biggest flaw.** Every agent receives the *identical* observation — a normalized
snapshot of the public book ([`state_helper.py`](../envs/exchg/state_helper.py) builds one
`stacked_obs` and hands the same array to every agent). Nothing in it encodes the agent's own
inventory, cash, NAV, drawdown, or resting orders. Yet the reward is NAV change, loss-scaled, minus
a drawdown penalty ([`reward_helper.py`](../envs/exchg/reward_helper.py)) — all functions of
unobserved private state.

The consequence is not "hard to learn," it is **ill-posed**: two states with identical books but
opposite inventory require opposite optimal actions and are indistinguishable to the policy.
`modify` and `cancel` are especially hopeless — the agent must decide whether to cancel an order it
cannot see. The README lists this as TODO #4, which understates it: this is not a nice-to-have
feature, it breaks the MDP.

### 1.2 No exogenous information process, so there is nothing to discover

Price starts at `randint(10, 100)`
([`continuousDoubleAuction_env.py`](../envs/continuousDoubleAuction_env.py)) and thereafter
random-walks on pure order flow. There is no fundamental value, no informed traders, no news, no
exogenous liquidity demand. The classic microstructure setups this wants to emulate (Kyle,
Glosten–Milgrom) all require informational asymmetry to generate meaningful price discovery,
spreads, and adverse selection. Without it, "profit" is purely redistribution among agents reacting
to each other, and the emergent LOB figures in the README are an artifact of the action-space
parameterization rather than of any market mechanism.

The environment is a valid *game*; the framing as a market simulator overreaches.

### 1.3 Zero-sum plus shaping produces a self-play signal that does not mean what the training code assumes

The accounting is genuinely zero-sum (`Decimal` throughout, NAV conserved). But the reward adds
order penalties, trade penalties, a drawdown penalty, and a passive-fill bonus, so **returns are no
longer zero-sum and no longer comparable across policies playing different roles**. The league
callback nevertheless ranks policies against a pooled `mean + k·std`
([`league_based_self_play_callback.py`](../train/callbk/league_based_self_play_callback.py)) that
includes random policies. A policy can clear the threshold by trading *less*, not by trading
*better*.

---

## 2. Design problems

### 2.1 The reward mixes a level with a delta

`nav_term` is a per-step *change*; `drawdown_penalty × current_drawdown` is a *level* re-charged in
full every step ([`reward_helper.py`](../envs/exchg/reward_helper.py)). An agent that draws down
once and then flatlines keeps paying `0.2 × drawdown` for the rest of the episode. Over a 1024-step
episode that term dwarfs everything else, and the optimal policy collapses to "never trade."

### 2.2 No reward scaling anywhere

The four hand-tuned coefficients (0.1 / 0.05 / 0.2 / 0.1) are summed against NAV changes of order
1e5–1e6, so they are numerically irrelevant *except* the drawdown term — which is the one that
should not be a level.

With `init_cash = 1e6`, rewards are ~1e6. The README's own sample output shows the consequence:
`vf_loss: 843138496.0`, `vf_explained_var: 0.0`. The value function never learned anything. That log
is presented as a successful result.

### 2.3 Two of the five action dimensions are degenerate

- **`size_sigma` is inert.** It is the standard deviation of
  `np.random.normal(mean_mul * mean, sigma)` where `mean_mul` is 49.5 or 499.5
  ([`action_helper.py`](../envs/exchg/action_helper.py)). It perturbs a size of up to 500 by less
  than one unit. The agent has a knob wired to nothing, and PPO will spend entropy exploring it
  forever.
- **`size_mean` is sign-folded.** It passes through `abs()`, so `−0.5` and `+0.5` produce identical
  orders. Half the action space is a redundant mirror, and the gradient has a kink at 0 — the worst
  possible place for one, since it is where a Gaussian policy initializes.

### 2.4 Order size is stochastic at execution time

The size the agent "chooses" is a random draw whose realization the agent never observes. Combined
with the shuffled execution order, the transition is stochastic in ways invisible to the policy —
extra variance in an already high-variance multi-agent setting, for no modelling benefit.

### 2.5 Silent no-ops give no learning signal

Rejected orders (insufficient cash, NAV ≤ 0) return empty lists
([`trader.py`](../envs/agent/trader.py)); `modify` and `cancel` against a non-existent order do
likewise. Nothing is logged, penalized, or surfaced in `infos`. Given that agents cannot see their
own resting orders (§1.1), a large and unmeasured fraction of all actions are probably no-ops — and
there is currently no way to know what that fraction is.

### 2.6 Bankrupt agents are never actually terminated

`set_done` adds to `done_set` but never sets the flag
([`done_helper.py`](../envs/exchg/done_helper.py)), and `set_all_done` then overwrites every
per-agent entry with `False`. A broke agent keeps being stepped, keeps sampling actions that
`_order_approved` silently rejects, and keeps collecting drawdown penalties. `__all__` only fires
when *everyone* is bankrupt.

### 2.7 Cooperative multiple inheritance used as a namespace-splitting device

`Exchg_Helper(State_Helper, Action_Helper, Reward_Helper, Done_Helper, Info_Helper)`, then
`continuousDoubleAuctionEnv(Exchg_Helper, MultiAgentEnv)`. The five mixins are not behavioural
variants — they are one class split five ways, sharing mutable state (`self.LOB`, `self.traders`,
`self.last_price`) with no declared contract. `State_Helper.__init__` drops kwargs on the way down
the chain, `Action_Helper.__init__(**kwargs)` swallows the rest, and whether `MultiAgentEnv.__init__`
runs at all depends on which mixin happens to lack an `__init__`. Composition
(`self.state = StateBuilder(...)`) would give the same file separation with an actual interface.

---

## 3. Implementation bugs (verified)

### 3.1 `custom_model: "model_disc"` is never registered — RESOLVED

Resolved in the Ray 2.56.1 upgrade. `custom_model` / `ModelCatalog` are not read at
all on the new API stack, so the indirection was removed rather than repaired.
Trainable modules use RLlib's default PPO module configured via
`DefaultModelConfig`; `league_policies.py` and `example_league_based_training.py`
were deleted.

### 3.2 The training code straddles two incompatible RLlib API stacks — RESOLVED

Resolved. The training layer is now entirely new-API-stack. `PolicySpec` wiring
was replaced by `MultiRLModuleSpec` in
[`policy_handler.py`](../train/policy/policy_handler.py); the broken
`CustomRLModule` (which read `config.action_space.n` against a `Dict` space) was
removed; `weight_handler.py` and `callbk_handler.py` were deleted as dead
old-stack code.

Note the failure mode here was worse than "does not run": RLlib accepted the
old-stack `policies` dict without error and silently substituted
`DefaultPPOTorchRLModule` for every declared `RandomPolicy`, so the baseline
opponents were frozen randomly-initialised networks rather than random samplers.
`test/integration/test_league_wiring.py` now asserts the module classes.

### 3.3 Champion selection likely reads a key that does not exist — RESOLVED

Confirmed and resolved. Neither `policy_reward_mean` nor `custom_metrics` exists
in `result[ENV_RUNNER_RESULTS]` on the new stack, so the mis-attributing
`agent_X → policy_X` fallback was the branch that ran. The callback now reads
`module_episode_returns_mean`, which is already keyed by real ModuleID
(`champion_*` included), so no remapping is needed.

### 3.4 The printed policy map is computed by different logic than the real one — RESOLVED

Resolved. `on_episode_start` now calls `get_mapping_fn` rather than
reimplementing selection, so the log reports the opponents actually played.
Selection also seeds from `zlib.crc32` instead of the builtin `hash()`, which is
salted per process and made the documented determinism hold only within a single
interpreter.

### 3.5 Champion snapshots never reached the EnvRunners — RESOLVED

Found during the Ray 2.56.1 upgrade; not in the original audit.

`_create_champion_snapshot_from_policy` called `add_module` and then `set_state`.
`add_module` syncs weights to the EnvRunners internally, but that happens *before*
the snapshot's weights are copied in, and PPO's per-iteration sync passes
`policies=modules_to_update`, which by design never contains a frozen champion.
The champion acting in the environment therefore stayed at its random
initialisation for the entire run while the trained snapshot sat unused in the
LearnerGroup.

Combined with 3.2, this meant the opponent pool was randomly-initialised networks
end to end: no self-play was taking place at all.

The callback now force-pushes champion state to the EnvRunners. This cannot go
via `sync_weights()` — that path carries the LearnerGroup's `WEIGHTS_SEQ_NO`, and
`EnvRunner.set_state` applies incoming module state only when the sequence number
is 0 or strictly ahead. Between two training updates the number is unchanged, so
such a sync is dropped silently.

### 3.6 Seeding is entirely non-functional

`reset(seed=...)` forwards to `MultiAgentEnv.reset`, which seeds `self._np_random` — which nothing
uses. The env draws from global `np.random` (initial price, order sizes) and
`sklearn.shuffle(actions, random_state=None)`, always passed `None`.

**No episode is reproducible.** For a research environment whose entire output is simulated data
this is disqualifying — none of the README's generated-LOB figures can be regenerated.

Relatedly, the league mapping's "deterministic selection" uses `hash(episode.id_)` on a string.
Python salts string hashes per process, so matchmaking differs across workers and across runs.

### 3.7 `tick_size` config is silently discarded

[`exchg_helper.py`](../envs/exchg/exchg_helper.py) uses it for the initial book, but `reset()`
hardcodes `OrderBook(1, ...)` and `self.tick_size` is never assigned anywhere.
`Action_Helper.min_tick = 1` is a second, independent hardcoded tick. Setting `tick_size` in
`env_config` does nothing after the first reset.

This is why `log1p_spread_ticks` is deliberately computed against `min_tick` rather than `tick_size`
— see [observation_space.md](observation_space.md) §3.2.

### 3.8 `sys.exit()` inside the matching engine

[`orderbook.py`](../envs/orderbook/orderbook.py) calls `sys.exit()` on several bad-input paths. A
library killing the interpreter takes down an RLlib rollout worker with a bare exit code and no
traceback. These should be exceptions.

### 3.9 Unbounded per-episode disk writes and monotonic league memory growth

`on_episode_step` accumulates every step's obs/act/reward/info in memory, and `on_episode_end`
pickles the lot to `episode_data/<id>.pkl` **unconditionally** — every episode, every worker, no cap,
no flag. A 100-iteration run writes thousands of files. `episode_data/` is also absent from
`.gitignore`, so it shows up as untracked noise after every run, including test runs.

`_remove_oldest_champion` never frees the removed module (acknowledged in a code comment), so league
memory grows monotonically.

### 3.10 `observation_space` / `action_space` are plain dicts, not Spaces

[`continuousDoubleAuction_env.py`](../envs/continuousDoubleAuction_env.py) assigns
`{agent_id: Box}`. Modern RLlib expects `observation_spaces` / `action_spaces`, or a
`gym.spaces.Dict`. Anything calling `env.observation_space.sample()` or `.contains()` breaks.
`self.agents = list(self._agent_ids)` also derives agent order from a `set` of salted-hash strings —
nondeterministic ordering across processes.

### 3.11 Rendering has side effects

`_render` nulls `model_actions` / `LOB_actions` / `shuffled_actions` and clears `seq_trades`.
Toggling `is_render` therefore changes state evolution. It also defaults to `True`, printing the
full book, tape, and every account on every step.

### 3.12 `Info_Helper` returns NAV as a string

[`info_helper.py`](../envs/exchg/info_helper.py) stringifies NAV to dodge `Decimal` serialization,
pushing `float()` parsing onto every consumer — which the league callback then does.

---

## 4. Engineering hygiene

- **CI is doubly dead.** `.travis.yml` targets a defunct service, pins Python 3.7.7, and runs
  `test_OrderBook.py` and `test_cda_nsp.py` — neither file exists. There is no `.github/`. The
  README still shows the Travis badge. The ~89 `unittest` cases are real work that nothing enforces.
- ~~**`setup.py` is broken for non-editable installs.**~~ RESOLVED: now uses
  `find_packages()` with real `install_requires` and extras; the bogus `YourEnvClass`
  entry point is gone and the missing `__init__.py` files were added, so the tests no
  longer need `PYTHONPATH`.
- **Stale entry points shipped as if current.** PARTIALLY RESOLVED:
  [`CDA_env_rand.py`](../CDA_env_rand.py) is fixed — it now takes a config dict, keys actions by
  agent ID, samples from the env's own action space, and is exercised in CI.
  [`random_agent.py`](../envs/agent/random_agent.py) still emits the old 5-tuple action from
  `select_random_action`; it is now unreferenced (nothing calls it) but has not been removed,
  because `Trader` still inherits from `Random_agent`.
- **Dead and duplicated modules.** MOSTLY RESOLVED: `policy_handler_0.py`, `weight_handler.py`,
  `callbk_handler.py`, `league_policies.py` and `example_league_based_training.py` were deleted,
  as were the duplicate/TF dockerfiles. Still outstanding: `state_diff`, `analyze_unused.py`
  shipped inside the package, `CODEOWNER` *and* `CODEOWNERS`. Large commented-out blocks (old `step`,
  old action space, old `modify_order`) preserved inline rather than in git history — which is what
  git history is for.
- **Documentation drift.** The README's Reward section describes a formula that no longer exists and
  asserts `episode_reward = 0` (zero-sum), which the current reward makes false. Older docs claimed
  "robust testing" while CI runs nothing, referenced a `test_orderbook.py` and a
  `repro_orderbook_crossed_book.py` that do not exist, and stated the order-approval check was
  NAV-only when a real cash check exists and is tested.

---

## 5. Observation-space problems

Specific to the observation pipeline. See [observation_space.md](observation_space.md) for what the
observation *is*.

### 5.1 Each frame in the stack is normalized by a different denominator

**The most serious observation defect, and specific to the interaction of the two most recent
changes.** `set_agg_LOB` computes `M` from the book *at that moment*, and `prep_next_state` appends
the already-normalized frame to the deque. So frames *t−3 … t* each carry their own `M_{t−3} … M_t`.

Consequence: **frames cannot be compared to each other.** A resting order whose absolute price never
changed appears to move whenever the midpoint moves; a real price move can appear as no change if
`M` moved with it. The entire purpose of stacking frames is to expose order flow — the *differences*
between frames — and those differences are contaminated by a time-varying normalizer that is not
itself observable.

**Fix:** keep raw snapshots in the deque and normalize the whole stack once, at emission, by the
current `M_t`. Additionally expose `M_t / M_{t−1} − 1` so the agent can reason about the anchor's own
motion.

*(Partially mitigated by the per-frame `log_mid` scalar, which at least lets the agent recover each
frame's normalizer.)*

### 5.2 Zero means three different things

`0.0` is the sentinel for "level absent." It is also the exact value of a price *at* the midpoint. On
a one-sided book `M` falls back to that side's L1 price, so `(M − P_bid_1)/M = 0` **exactly** — the
best bid in a bid-only book is numerically identical to an empty level. The same holds for an
ask-only book.

This is not a corner case: the book starts empty every episode and is frequently one-sided early on.
There is no validity mask, so the network cannot disambiguate.

**Fix:** an explicit per-level occupancy channel (10 bits per side), or a clearly out-of-range
sentinel.

### 5.3 The tape loop is dead code — there is no trade-flow information at all

In [`state_helper.py`](../envs/exchg/state_helper.py):

```python
if self.LOB.tape != None and len(self.LOB.tape) > 0:
    num = 0
    for entry in reversed(self.LOB.tape):
        if num < self.LOB.tape_display_length:
            #tempfile.write(...)
            num += 1
        else:
            break
```

`entry` is never used. The body is a commented-out `write` copy-pasted from `OrderBook.__str__`. The
loop increments a counter and discards it. It *looks* like it is building tape features; it builds
nothing.

The observation therefore contains **zero information about executions**: no last traded price, no
trade direction, no signed volume, no trade count. In a continuous double auction, aggressive order
flow is the single most predictive public signal — more so than the resting book, which is largely
stale intentions. This is the largest missing feature, and the placeholder loop suggests it was
intended to be there.

### 5.4 The price anchor was discarded — partially fixed

Normalization is scale-free by design, so `M` was not in the observation. Combined with `last_price`
being drawn uniformly from [10, 100] each episode, this created a concrete pathology: tick size is
absolute (`min_tick = 1`) but the observation was relative, so `price_offset` was ten times more
aggressive at `M = 10` than at `M = 100` — and the two situations were literally indistinguishable.

**Addressed** by the `log_mid` feature ([observation_space.md](observation_space.md) §3.1). What
remains unaddressed: price distances are still expressed as fractions rather than ticks, so
observation units still do not match action units. Also, at `t = 0` the book is empty, so the book
block is all zeros in **every** episode and the first action is necessarily uninformed.

### 5.5 Feature scales differ by ~600× after "normalization"

Using the README's own example book (bids 23…9, asks 36…48, `M ≈ 29.5`, sizes 7,746…188,096):

| Block | Range |
|---|---|
| Normalized prices | −0.63 … +0.69 |
| `sqrt(volume)` sizes | −434 … +434 |
| `log_mid`, `log1p_spread_ticks` | 0 … 4.6 |

All 22 well-scaled features feed the same linear layer as the 20 size features and are two to three
orders of magnitude smaller. The price half is effectively invisible at initialization. `sqrt`
stabilized variance *within* the size block and left the cross-block mismatch untouched — arguably
worse than no normalization, because the documentation now asserts the observation is normalized.

**Fix:** give size the same units-free property as price — `V_k / sum(V)` (depth share),
`log1p(V)`, or `V` divided by a running mean. `sqrt` of an unbounded raw count is not a
normalization.

This is also why a null result from the `log_mid` / `log1p_spread_ticks` features would not prove
those features useless — they are correct, but likely dominated until the size block is rescaled.

### 5.6 Level index is a non-stationary coordinate

Position *k* in the vector means "the *k*-th occupied price," not a fixed price. In the README
example, bid levels 0–9 span prices 23 down to 9; the mapping from index to distance-from-mid
changes every step as levels are created and consumed. The action space selects by the **same**
unstable index, so a learned association such as "level 3 is a good place to quote" has no fixed
meaning across steps.

**Fix:** a fixed grid — one slot per tick offset from the midpoint, out to ±N ticks, holding the
volume at that price. This is stationary, makes empty levels naturally zero-volume rather than
sentinel-encoded, and makes observation and action share one coordinate system. Ranked second in
priority after adding private state.

### 5.7 Redundancy and wasted capacity

- **The sign convention is redundant.** Side is already encoded by block position; negating asks
  adds no information. It does prevent weight sharing between the two sides, which is otherwise a
  natural symmetry to exploit.
- **4× stacking of slowly-changing absolute levels.** Consecutive frames are near-identical, so
  roughly 120 of the 160 book dimensions are near-duplicates, while the informative quantity (the
  change) must be recovered as a difference of large, similar numbers — poor conditioning. A
  `state_diff` function that computes exactly this already exists, unused, with a comment saying it
  "should be used in obs preprocessing if needed." Either use it or delete it.
- **`Box(-inf, inf)` bounds.** Every quantity here is boundable. Infinite bounds disable RLlib's
  observation filters and any space-based sanity checking, and signal that the range was never
  analyzed.
- **Whatever survives is squeezed through `Linear(160, 8)`** in
  [`model_handler.py`](../train/model/model_handler.py). Even a well-designed observation cannot pass
  through an 8-unit bottleneck.

### 5.8 A test cements the design flaw

`test_shared_history_multi_agent_uniformity` asserts that all agents receive byte-identical
observations. That is currently true, but writing it as a test encodes an implementation accident as
a requirement. The moment private state is added, this test must be deleted.

The normalization tests are otherwise sound — signs, `sqrt` correctness, NaN/Inf safety on empty
books, the raw-price action mapping. What they do not check is anything about *information content*,
which is where the problems are. The suite would pass unchanged with the dead tape loop, the
varying-denominator stack, and the zero collision all present — and all three are present.

### 5.9 A recommended layout

Roughly, per frame, all in tick units and depth shares:

```
market (public):
  log(M)                                    1    restores the anchor  [DONE]
  spread in ticks                           1                         [DONE]
  volume at +/-N tick offsets from mid     2N    fixed grid, stationary
  occupancy mask for that grid             2N    kills the zero collision
  signed traded volume last step            1    from the tape
  trade count / direction last step         2
  M_t / M_{t-1} - 1                         1    lets the agent undo rescaling

private (per agent):
  net position, VWAP, unrealized P&L        3
  cash, cash_on_hold, NAV/init_cash         3
  drawdown from peak                        1
  own resting volume on the same grid      2N
  t_step / max_step                         1
```

Also missing and cheap: **time remaining** (`t_step / max_step`). This is a finite-horizon episode,
so the optimal policy is genuinely time-dependent — inventory should be flattened toward the end —
and the agent cannot condition on it.

Stack raw snapshots, normalize the whole stack once at emission using the current `M_t`, and add
explicit frame deltas rather than relying on the network to difference them.

---

## 6. What is actually good

Worth stating, since the list above is long.

- The matching engine is a faithful price–time-priority implementation with a sensible data
  structure choice (`SortedDict` of intrusive linked lists).
- The `Decimal` accounting with escrowed `cash_on_hold` is carefully done, and the NAV-conservation
  invariant is real and checked at runtime.
- Position-flip handling (`_covered_side_chg`) is the case most toy exchanges get wrong, and it has
  four dedicated tests.
- The ~89 unit tests cover genuinely tricky ground — crossed books, volume sync, modify-order
  priority semantics, observation normalization.
- Temporal stacking, and the raw/normalized book split (`agg_LOB_raw` for action resolution,
  normalized for observation), are both correct instincts.
- The deterministic ghost-level pricing that replaced the old random-price fallback is a genuine
  improvement, correctly motivated and well tested.

The problem is a sharp quality gradient: the market engine is well-engineered, and the RL layer
wrapped around it — observation content, reward shaping, action parameterization, and the entire
training stack — is where the defects concentrate.

---

## 7. Priority order

### If you fix five things

1. **Put private state in the observation** — net position, cash, NAV, drawdown, and the agent's own
   resting orders. Nothing else on this list matters until the MDP is well-posed (§1.1).
2. **Make seeding work** — one `np.random.Generator` on the env, threaded through size sampling,
   initial price, and `rand_exec_seq`. Without it no result is checkable (§3.6).
3. **Rework the reward** — normalize by `init_cash`, make drawdown a *delta* not a level, drop or
   drastically rescale the hand-tuned constants (§2.1, §2.2).
4. **Pick one RLlib API stack** and delete the other; register `model_disc` or stop referencing it.
   Then get one end-to-end training run to actually complete (§3.1, §3.2).
5. **Add GitHub Actions running the existing tests** — the suite already exists and is decent; it is
   just unenforced (§4).

Then fix the degenerate action dimensions (§2.3) and surface rejected/no-op orders in `infos`
(§2.5), so the fraction of actions doing nothing becomes measurable.

### Observation-specific order

| # | Change | Category |
|---|---|---|
| 1 | Add private state (position, cash, NAV, VWAP, drawdown, own resting orders) | correctness |
| 2 | Normalize the whole stack by the current `M_t`; stop storing pre-normalized frames | correctness |
| 3 | Finish the dead tape loop — add trade-flow features | correctness |
| 4 | Fixed tick-offset price grid shared with the action space | conditioning |
| 5 | Replace `sqrt(V)` with a units-free size normalization | conditioning |
| 6 | Occupancy mask; expose `t_step / max_step`; finite `Box` bounds | conditioning |

Items 1–3 are correctness: without them the observation is missing information the policy provably
needs. Items 4–6 are conditioning: the information is present but presented in a form that makes it
hard to use.
