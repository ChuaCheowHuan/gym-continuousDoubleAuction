# Problems Identified (generated 2026-08-10 07:02:26)

A critique of `gym-continuousDoubleAuction` across intent, concept, design and implementation.
Companion to [`codebase_analysis_20260810_065207.md`](codebase_analysis_20260810_065207.md), which
describes how the system works. This document describes what is wrong with it.

Findings are ordered by cost, not by layer. All file/line references were verified against the
tree at commit `115731e` (branch `relative_orderbook`).

---

## 1. Conceptual problems (the deepest ones)

### 1.1 Agents cannot see their own state, but the reward depends entirely on it

This is the single biggest flaw. Every agent receives the *identical* observation — a normalized
snapshot of the public book ([`state_helper.py:22`](../envs/exchg/state_helper.py) builds one
`stacked_obs` and hands the same array to all agents). Nothing in the 160 floats encodes the
agent's own inventory, cash, NAV, drawdown, or resting orders. Yet the reward is NAV change,
loss-scaled, minus a drawdown penalty ([`reward_helper.py:40`](../envs/exchg/reward_helper.py)) —
all functions of unobserved private state.

The consequence is not "hard to learn," it is *ill-posed*: two states with identical books but
opposite inventory require opposite optimal actions and are indistinguishable to the policy.
`modify` and `cancel` are especially hopeless — the agent must decide whether to cancel an order
it cannot see. The README lists this as TODO #4, which understates it: this is not a
nice-to-have feature, it breaks the MDP.

### 1.2 No exogenous information process, so there is nothing to discover

Price starts at `randint(10, 100)`
([`continuousDoubleAuction_env.py:166`](../envs/continuousDoubleAuction_env.py)) and thereafter
random-walks on pure order flow. There is no fundamental value, no informed traders, no news, no
exogenous liquidity demand. The classic microstructure setups this wants to emulate
(Kyle, Glosten–Milgrom) all require informational asymmetry to generate meaningful price
discovery, spreads, and adverse selection. Without it, "profit" is purely redistribution among
agents reacting to each other, and the emergent LOB figures in the README are an artifact of the
action-space parameterization rather than of any market mechanism.

The environment is a valid *game*; the framing as a market simulator overreaches.

### 1.3 Zero-sum + shaping = a self-play signal that does not mean what the training code assumes

The accounting is genuinely zero-sum (`Decimal` throughout, NAV conserved). But the reward adds
order penalties, trade penalties, a drawdown penalty and a passive-fill bonus, so *returns are no
longer zero-sum and no longer comparable across policies playing different roles*. The league
callback nevertheless ranks policies against a pooled `mean + k·std`
([`league_based_self_play_callback.py:355`](../train/callbk/league_based_self_play_callback.py))
that includes random policies. A policy can clear the threshold by trading less, not by trading
better.

---

## 2. Design problems

### 2.1 The reward mixes a level with a delta

`nav_term` is a per-step *change*; `drawdown_penalty * current_drawdown` is a *level* re-charged in
full every single step ([`reward_helper.py:37-44`](../envs/exchg/reward_helper.py)). An agent that
draws down once and then flatlines keeps paying `0.2 × drawdown` for the rest of the episode. Over
a 1024-step episode that term dwarfs everything else, and the optimal policy collapses to "never
trade."

The four hand-tuned coefficients (0.1 / 0.05 / 0.2 / 0.1) are also being summed against NAV changes
of order 1e5–1e6, so they are numerically irrelevant *except* the drawdown term — which is the one
that should not be a level.

### 2.2 No reward scaling anywhere

With `init_cash = 1e6`, rewards are ~1e6. The README's own sample output shows the consequence:
`vf_loss: 843138496.0`, `vf_explained_var: 0.0`. The value function never learned anything. That
log is presented as a successful result.

### 2.3 Two of the five action dimensions are degenerate

- **`size_sigma` is inert.** It is the std of `np.random.normal(mean_mul * mean, sigma)` where
  `mean_mul` is 49.5 or 499.5 ([`action_helper.py:221`](../envs/exchg/action_helper.py)). It
  perturbs a size of up to 500 by less than one unit. The agent has a knob wired to nothing, and
  PPO will spend entropy exploring it forever.
- **`size_mean` is sign-folded.** It passes through `abs()`
  ([`action_helper.py:226`](../envs/exchg/action_helper.py)), so `-0.5` and `+0.5` produce
  identical orders. Half the action space is a redundant mirror, and the gradient is non-smooth at
  0 — the worst place to put a kink, since it is where a Gaussian policy initializes.

### 2.4 Order size is stochastic at execution time

The size the agent "chooses" is a random draw whose realization the agent never observes. Combined
with the shuffled execution order, the transition is stochastic in ways invisible to the policy —
extra variance in an already high-variance multi-agent setting, for no modelling benefit.

### 2.5 Silent no-ops give no learning signal

Rejected orders (insufficient cash, NAV <= 0) return empty lists
([`trader.py:61-66`](../envs/agent/trader.py)); `modify`/`cancel` against a non-existent order
likewise ([`trader.py:171-177`](../envs/agent/trader.py)). Nothing is logged, penalized, or
surfaced in `infos`. Given that agents cannot see their own resting orders (§1.1), a large and
unmeasured fraction of all actions are probably no-ops — and there is currently no way to know
what that fraction is.

### 2.6 Bankrupt agents are never actually terminated

`set_done` adds to `done_set` but never sets the flag
([`done_helper.py:15-18`](../envs/exchg/done_helper.py)), and `set_all_done` then overwrites every
per-agent entry with `False` ([`done_helper.py:32`](../envs/exchg/done_helper.py)). A broke agent
keeps being stepped, keeps sampling actions that `_order_approved` silently rejects, and keeps
collecting drawdown penalties. `__all__` only fires when *everyone* is bankrupt.

### 2.7 Cooperative multiple inheritance used as a namespace-splitting device

`Exchg_Helper(State_Helper, Action_Helper, Reward_Helper, Done_Helper, Info_Helper)`, then
`continuousDoubleAuctionEnv(Exchg_Helper, MultiAgentEnv)`. The five mixins are not behavioral
variants — they are one class split five ways, sharing mutable state (`self.LOB`, `self.traders`,
`self.last_price`) with no declared contract. `State_Helper.__init__` drops kwargs on the way down
the chain, `Action_Helper.__init__(**kwargs)` swallows the rest, and whether `MultiAgentEnv.__init__`
runs at all depends on which mixin happens to lack an `__init__`. Composition
(`self.state = StateBuilder(...)`) would give the same file separation with an actual interface.

---

## 3. Implementation bugs (verified)

### 3.1 `custom_model: "model_disc"` is never registered

Referenced in [`policy_handler.py:45`](../train/policy/policy_handler.py),
[`league_policies.py:11`](../train/policy/league_policies.py),
[`example_league_based_training.py:42`](../train/callbk/example_league_based_training.py). There is
no `ModelCatalog.register_custom_model` / `register_custom_model` call anywhere in the repo
(grepped). Every training entry point using these configs fails at build time.

### 3.2 The training code straddles two incompatible RLlib API stacks

- `PolicySpec` + `custom_model` (old stack) in [`policy_handler.py`](../train/policy/policy_handler.py)
- `algorithm.get_module` / `add_module` / `RLModuleSpec` (new stack) in the league callback
- both in the same script in
  [`example_league_based_training.py`](../train/callbk/example_league_based_training.py)

Additionally [`model_handler.py`](../train/model/model_handler.py) does `config.action_space.n` —
the action space is a `Dict`, which has no `.n`. And
[`weight_handler.py:25`](../train/weight/weight_handler.py) reads `result["hist_stats"]`,
[`callbk_handler.py:11`](../train/callbk/callbk_handler.py) reads `episode.user_data` — both
removed from modern RLlib. The env is modernized; the training layer around it is a stratigraphy of
three eras, and it is not clear any single path through it runs.

### 3.3 Champion selection likely reads a key that does not exist, with a wrong fallback

[`league_based_self_play_callback.py:325`](../train/callbk/league_based_self_play_callback.py) looks
for `result['env_runners']['policy_reward_mean']` — an old-stack key. The fallback maps
`agent_X -> policy_X`, which is precisely the assumption league play breaks: `agent_2` may be
playing `champion_1`. The fallback therefore attributes a champion's return to `policy_2`.
Champion promotion is driven by mis-attributed numbers.

### 3.4 The printed policy map is computed by different logic than the real one

`on_episode_start` uses `(hash(episode.id_) + i) % len(candidates)`
([line 99](../train/callbk/league_based_self_play_callback.py)); the actual mapping uses a weighted
`RandomState.choice` ([line 562](../train/callbk/league_based_self_play_callback.py)). The debug
output telling you who played whom is wrong. A code comment flags the divergence instead of fixing
it.

### 3.5 Seeding is entirely non-functional

`reset(seed=...)` forwards to `MultiAgentEnv.reset`, which seeds `self._np_random` — which nothing
uses. The env draws from global `np.random` (initial price, order sizes) and
`sklearn.shuffle(actions, random_state=None)`
([`action_helper.py:96`](../envs/exchg/action_helper.py), always passed `None` at
[`continuousDoubleAuction_env.py:233`](../envs/continuousDoubleAuction_env.py)).

No episode is reproducible. For a research environment whose entire output is simulated data this
is disqualifying — none of the README's generated-LOB figures can be regenerated.

Relatedly, the league mapping's "deterministic selection" uses `hash(episode.id_)` on a string
([line 562](../train/callbk/league_based_self_play_callback.py)). Python salts string hashes per
process, so matchmaking differs across workers and across runs.

### 3.6 `tick_size` config is silently discarded

[`exchg_helper.py:18`](../envs/exchg/exchg_helper.py) uses it for the initial book, but `reset()`
hardcodes `OrderBook(1, ...)` ([`continuousDoubleAuction_env.py:141`](../envs/continuousDoubleAuction_env.py))
and `self.tick_size` is never assigned anywhere. `Action_Helper.min_tick = 1` is a second,
independent hardcoded tick. Setting `tick_size` in `env_config` does nothing after the first reset.

### 3.7 Observation features differ by three orders of magnitude *after* normalization

Normalized prices are `(M-P)/M` ~ 0.01–0.5; normalized sizes are `sqrt(volume)` ~ 30–300 for the
volumes this env generates ([`state_helper.py:126-131`](../envs/exchg/state_helper.py)). They are
concatenated into one vector feeding a `Linear(160, 8)`. The price half is invisible. The `sqrt`
fixed variance *within* the size block and left the cross-block scale mismatch untouched —
arguably worse than no normalization, because the docs now claim the observation is normalized.

There is also an inversion worth questioning: `(M - P_bid)/M` gives the *least* relevant levels
(deep in the book) the *largest* magnitude, and squashes the touch — the most informative levels —
toward zero.

### 3.8 `sys.exit()` inside the matching engine

[`orderbook.py`](../envs/orderbook/orderbook.py) lines 39, 55, 151, 185, 200. A library killing the
interpreter on bad input takes down an RLlib rollout worker with a bare exit code and no traceback.
These should be exceptions.

### 3.9 Unbounded per-episode disk writes from the callback

`on_episode_step` accumulates every step's obs/act/reward/info in memory, and `on_episode_end`
pickles the lot to `episode_data/<id>.pkl` unconditionally
([lines 255-258](../train/callbk/league_based_self_play_callback.py)) — every episode, every
worker, no cap, no flag. A 100-iteration run writes thousands of files. `_remove_oldest_champion`
similarly never frees the module (acknowledged in a comment at
[line 493](../train/callbk/league_based_self_play_callback.py)), so league memory grows
monotonically.

### 3.10 `observation_space` / `action_space` are plain dicts, not Spaces

[`continuousDoubleAuction_env.py:70`](../envs/continuousDoubleAuction_env.py) and
[line 83](../envs/continuousDoubleAuction_env.py) assign `{agent_id: Box}`. Modern RLlib expects
`observation_spaces`/`action_spaces`, or a `gym.spaces.Dict`. Anything calling
`env.observation_space.sample()` or `.contains()` breaks. `self.agents = list(self._agent_ids)`
also derives agent order from a `set` of salted-hash strings — nondeterministic ordering across
processes.

### 3.11 Rendering has side effects

`_render` nulls `model_actions`/`LOB_actions`/`shuffled_actions` and clears `seq_trades`
([`continuousDoubleAuction_env.py:268`](../envs/continuousDoubleAuction_env.py),
[line 284](../envs/continuousDoubleAuction_env.py)). Toggling `is_render` changes state evolution.
It also defaults to `True`, printing the full book, tape, and every account on every step.

### 3.12 `Info_Helper` returns NAV as a string

[`info_helper.py:18`](../envs/exchg/info_helper.py) stringifies NAV to dodge `Decimal`
serialization, pushing `float()` parsing onto every consumer — which the callback then does at
[line 303](../train/callbk/league_based_self_play_callback.py).

---

## 4. Engineering hygiene

- **CI is doubly dead.** `.travis.yml` targets a defunct service, pins Python 3.7.7, and runs
  `test_OrderBook.py` and `test_cda_nsp.py` — neither file exists. There is no `.github/`. The
  README still shows the Travis badge. The 72 `unittest` cases are real work that nothing enforces.
- **`setup.py` is broken for non-editable installs.** `packages=['gym_continuousDoubleAuction']`
  omits every subpackage (`envs`, `train`, `envs.orderbook`, ...), and `entry_points` still says
  `YourEnvClass`. Only `pip install -e .` works, by accident.
- **Stale entry points shipped as if current.** [`CDA_env_rand.py`](../CDA_env_rand.py) uses the
  pre-config positional constructor and iterates `e.agents` as trader objects;
  [`random_agent.py`](../envs/agent/random_agent.py) emits the old 5-tuple action. Both are dead on
  arrival against the current API, and the README recommends the former as a way to run the
  project.
- **Dead and duplicated modules.** `policy_handler.py` vs `policy_handler_0.py`, `weight_handler.py`
  (superseded by the league callback), `callbk_handler.py`, `state_diff`, `analyze_unused.py`
  shipped inside the package, `CODEOWNER` *and* `CODEOWNERS`. Large commented-out blocks (old
  `step`, old action space, old `modify_order`) preserved inline rather than in git history — which
  is what git history is for.
- **Documentation drift.** The README's Reward section describes a formula that no longer exists and
  asserts `episode_reward = 0` (zero-sum), which the current reward function makes false.
  `doc/change.md` claims "Robust Testing" while CI runs nothing.

---

## 5. What is actually good

Worth stating, since the list above is long.

- The matching engine is a faithful price–time-priority implementation with a sensible data
  structure choice (`SortedDict` of intrusive linked lists).
- The `Decimal` accounting with escrowed `cash_on_hold` is carefully done, and the NAV-conservation
  invariant is real and checked.
- Position-flip handling (`_covered_side_chg`) is the case most toy exchanges get wrong, and it has
  four dedicated tests.
- The 72 unit tests cover genuinely tricky ground — crossed books, volume sync, modify-order
  priority semantics.
- Temporal stacking, and the raw/normalized book split (`agg_LOB_raw` for action resolution,
  normalized for observation), are both correct instincts.

The problem is a sharp quality gradient: the market engine is well-engineered, and the RL layer
wrapped around it — observation content, reward shaping, action parameterization, and the entire
training stack — is where the defects concentrate.

---

## 6. If you fix five things

1. **Put private state in the observation** — net position, cash, NAV, drawdown, and the agent's own
   resting orders. Nothing else on this list matters until the MDP is well-posed (§1.1).
2. **Make seeding work** — one `np.random.Generator` on the env, threaded through size sampling,
   initial price, and `rand_exec_seq`. Without it no result is checkable (§3.5).
3. **Rework the reward** — normalize by `init_cash`, make drawdown a *delta* not a level, drop or
   drastically rescale the hand-tuned constants (§2.1, §2.2).
4. **Pick one RLlib API stack** and delete the other; register `model_disc` or stop referencing it.
   Then get one end-to-end training run to actually complete (§3.1, §3.2).
5. **Add GitHub Actions running the existing tests** — the suite already exists and is decent; it is
   just unenforced (§4).

Then fix the degenerate action dimensions (§2.3) and surface rejected/no-op orders in `infos`
(§2.5), so the fraction of actions doing nothing becomes measurable.
