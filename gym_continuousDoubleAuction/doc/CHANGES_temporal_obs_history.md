# Temporal Observation History Stacking — Change Log

## Overview

This document records all changes made to the `gym-continuousDoubleAuction` MARL codebase in this session. The primary goal was to implement a **temporal history-stacking mechanism** for environment observations, replacing the single-step orderbook snapshot with a sliding window of the last *N* sequential observations. Secondary goals were to fix cooperative multiple inheritance bugs exposed by the change and to ensure all unit tests pass using the standard library.

---

## 1. Motivation

### Why add temporal history stacking?

A single orderbook snapshot at time *t* gives agents no information about **how the market arrived at its current state** — whether prices are trending, order flow is accelerating, or a large order is being worked. Providing agents with a window of the *N* most recent snapshots enables:

- Learning temporal patterns (e.g. momentum, mean-reversion)
- Distinguishing between a stable book and a rapidly evolving one
- Better alignment with how human traders process information

### Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Observation format | Flat 1D vector `(N × 40,)` | Maximum compatibility with RLlib built-in policies (FCNet, LSTM expect flat inputs) |
| History scope | Shared environment-level `obs_history` deque | All agents observe the same market; per-agent history would be redundant |
| Default window size *N* | 4 | Balances temporal context vs. input dimensionality |
| Configurability | Via `config["n_hist"]` | Consistent with existing RLlib config pattern |

---

## 2. Files Changed

### 2.1 `gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py`

**What changed:**
- Added `self.n_hist = config.get("n_hist", 4)` to extract the history window size from config.
- Passed `n_hist=self.n_hist` into `super().__init__(...)`.
- Updated `self.observation_space` shape from `(40,)` to `(self.n_hist * 40,)` for all agents.

**Why:** The environment is the top-level entry point for RLlib; the observation space declaration must match the actual observations returned by `reset()` and `step()`.

---

### 2.2 `gym_continuousDoubleAuction/envs/exchg/state_helper.py`

**What changed:**
- Added `from collections import deque`.
- Updated `State_Helper.__init__(self, n_hist=4, **kwargs)` to store `self.n_hist` and initialise `self.obs_history = deque(maxlen=self.n_hist)`. Calls `super().__init__()` (without forwarding kwargs, to avoid passing unexpected arguments to `object.__init__`).
- `reset_traders_agg_LOB()`: Generates the initial LOB snapshot *O₀* via `set_agg_LOB()`, then fills `self.obs_history` with *N* copies of *O₀* (padding). Concatenates the deque into a flat 1D array `(N × 40,)` and returns it as the identical observation for every agent.
- `prep_next_state()`: Appends the new snapshot *O_t* to `self.obs_history` (automatically dropping the oldest). Concatenates and returns the stacked 1D array.

**Why:** Centralising history management in `State_Helper` keeps observation construction in one place. Using `deque(maxlen=N)` provides automatic sliding-window behaviour without manual index tracking. Padding with *N* copies of *O₀* on reset avoids zero-padding that could mislead agents into thinking there was no activity.

---

### 2.3 `gym_continuousDoubleAuction/envs/exchg/action_helper.py`

**What changed:**
- Updated `Action_Helper.__init__(self, **kwargs)` to:
  1. Set all action space attributes (`min_size`, `mkt_max_size`, `N`, `limit_max_size`, `mkt_size_mean_mul`, `limit_size_mean_mul`, `min_tick`, `max_price`, `last_price`) **before** calling `super().__init__()`.
  2. Call `super().__init__()` (without `**kwargs`, as it is the last user-defined class before `object` in the MRO chain).

**Why (root cause):** Python's cooperative multiple inheritance (MRO) requires every `__init__` in the chain to call `super().__init__()`. Previously, when `State_Helper.__init__` called `super().__init__(**kwargs)` with leftover kwargs such as `n_hist=4`, this eventually reached `object.__init__(n_hist=4)`, which raises `TypeError`. This aborted the `Action_Helper.__init__` body mid-execution before `self.min_tick = 1` was reached — causing `AttributeError: 'continuousDoubleAuctionEnv' object has no attribute 'min_tick'`.

The fix is to ensure each class in the MRO chain **consumes its own kwargs** and passes `super().__init__()` with no unexpected arguments by the time `object` is reached.

---

### 2.4 `gym_continuousDoubleAuction/envs/exchg/exchg_helper.py`

**What changed:**
- Updated `Exchg_Helper.__init__(self, init_cash=0, tick_size=1, tape_display_length=10, n_hist=4)` to accept `n_hist` as an explicit parameter and forward it as `super().__init__(n_hist=n_hist)` so `State_Helper` receives it.
- Updated `print_table(self, msg, data)` to detect when `data` is a flat 1D numpy array and reshape it into a human-readable 4-column table (`bid_price | bid_size | ask_price | ask_size`) before passing to `tabulate`.

**Why `print_table` needed fixing:** `set_agg_LOB()` now returns a flat `(40,)` numpy array (changed from the original list-of-arrays format to produce a concatenated observation vector). The `_render()` method passes `self.agg_LOB` directly to `print_table` → `tabulate`. When `tabulate` receives a 1D array it iterates over 40 individual `numpy.float32` scalars as "rows", and then tries to iterate each scalar — producing `TypeError: 'numpy.float32' object is not iterable`. The fix detects the 1D case and reshapes into 4 columns of 10 rows (one per price level) before display.

---

### 2.5 `gym_continuousDoubleAuction/visualize/visualize_orderbook.py`

**What changed:**
- Updated observation parsing to extract `latest_snapshot = agent_obs[-40:]` instead of using the full observation vector.

**Why:** The visualization only needs the most recent orderbook snapshot to render the current book state. Taking the last 40 elements is compatible with both the old `(40,)` observations and the new `(N × 40,)` stacked observations.

---

### 2.6 `gym_continuousDoubleAuction/test/test_observation_history.py` *(new file)*

**What was added:** A `unittest`-based test suite (no pytest dependency) covering:

| Test | What it verifies |
|---|---|
| `test_default_n_hist_observation_space` | Default `n_hist=4` yields `observation_space` shape `(160,)` and `reset()` obs shape `(160,)`. Also checks `mkt_size_mean_mul` is initialised (MRO chain health check). |
| `test_configurable_n_hist` | `n_hist ∈ {1, 2, 6, 10}` correctly resizes the observation space to `(N × 40,)`. |
| `test_reset_padding_identical_copies` | All *N* temporal segments in the reset observation are identical copies of *O₀* (no zero-padding artefacts). |
| `test_sliding_window_updates` | After each `step()`, the trailing 40 elements match the latest snapshot; observation shape stays `(N × 40,)` throughout. |
| `test_shared_history_multi_agent_uniformity` | All agents receive the same observation at reset and after each step (shared market view). |

**Why `unittest` instead of `pytest`:** The notebook environment (`%run`) does not have `pytest` installed. Using only the Python standard library ensures the tests run directly from the notebook without installation.

---

## 3. Class Hierarchy & MRO

```
continuousDoubleAuctionEnv
    └── Exchg_Helper
            └── State_Helper      ← consumes n_hist, calls super().__init__()
                    └── Action_Helper  ← initialises min_tick, mkt_size_mean_mul, etc.
                            └── Reward_Helper
                                    └── Done_Helper
                                            └── Info_Helper
                                                    └── object
```

**Key rule:** Every `__init__` in the chain must call `super().__init__()`. Each class must consume its own keyword arguments and must **not** forward unrecognised kwargs to `object.__init__`.

---

## 4. How to Run the Tests

From within `test.ipynb`:
```python
%run ../gym_continuousDoubleAuction/test/test_observation_history.py
%run ../gym_continuousDoubleAuction/test/test_new_action_space.py
```

Expected output for each:
```
.....
----------------------------------------------------------------------
Ran N tests in X.XXXs

OK
```

Or from the terminal at the workspace root:
```bash
python gym_continuousDoubleAuction/test/test_observation_history.py
python gym_continuousDoubleAuction/test/test_new_action_space.py
```

---

## 5. Observation Vector Layout

For `n_hist = 4` (default), the observation returned per agent is a flat array of shape `(160,)`:

```
[ O_{t-3} | O_{t-2} | O_{t-1} | O_t ]
  ──────────────────────────────────
  each segment Oₖ is 40 floats:
    [bid_price × 10, bid_size × 10, ask_price × 10, ask_size × 10]
  (ask prices and sizes are stored as negatives)
```

The most recent snapshot is always the **last 40 elements** (`agent_obs[-40:]`).
