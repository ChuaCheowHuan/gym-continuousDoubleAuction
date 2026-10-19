"""TrainConfig: every training knob, read from config/train_config.json (issue #254).

Split out of `train.train` so the config can be imported and tested without building an
algorithm. `train.train` re-exports every public name.
"""

from __future__ import annotations
import copy
import dataclasses
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import torch
from gym_continuousDoubleAuction.config_loader import flat_view, flatten
from gym_continuousDoubleAuction.envs.settings import EnvSettings
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.callbk.league import PROMOTION_REFERENCES
from gym_continuousDoubleAuction.train.model.encoders import validate_encoder_type

logger = get_logger("gym_continuousDoubleAuction.train.train")


ENV_NAME = "continuousDoubleAuction-v0"


#: The file every TrainConfig default is read from.
TRAIN_CONFIG_FILE = "train_config.json"


#: Per-iteration result dicts, one JSON object per line, under `run_dir`.
#: `algo.train()` returns a full metrics dict every iteration and the loop used
#: to read two keys out of it for a log line and drop the rest, so a finished
#: run left behind checkpoints and no record of how it got there. This is the
#: record. See docs/11 1.6.
PROGRESS_FILE = "progress.jsonl"


#: How long the driver waits for the runners to accept a new iteration tag.
#: Short and non-fatal: this is a log field, and a runner that is slow to answer
#: must delay sampling by as little as possible. Missing it costs `iter=-` on
#: that runner's lines for one iteration, nothing more.
_BROADCAST_TIMEOUT_S = 10.0


def generate_run_id() -> str:
    """A directory name unique to this run: local date, time, four hex digits.

    The timestamp is what makes a listing readable and orderable; the random
    suffix is what makes it *unique*, because two runs launched by the same
    script in the same second would otherwise collide on the second - which is
    exactly the shared-directory case `run_dir` exists to prevent.

    Local time rather than UTC, to match the log timestamps a reader is
    correlating this against.
    """
    return f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"


#: `result["learners"][<module_id>]["vf_explained_var"]`: the fraction of return
#: variance the critic accounts for. Defined by RLlib as
#: `ppo.LEARNER_RESULTS_VF_EXPLAINED_VAR_KEY` and written by PPOTorchLearner;
#: spelled out here rather than imported so a rename in Ray degrades to a
#: missing metric instead of an ImportError that stops training. A critic stuck
#: near 0.0 is the failure this exists to make visible while a run is going,
#: which no amount of reading `module_episode_returns_mean` will show.
VF_EXPLAINED_VAR_KEY = "vf_explained_var"


def _default(key: str, *, compare: bool = True):
    """A dataclass default read from `config/train_config.json`.

    The value is fetched when a TrainConfig is instantiated, not when this
    module is imported, so a config tree swapped in via `$CDA_CONFIG_DIR` takes
    effect without re-importing. A key missing from the file raises: the
    dataclass declares the schema, the file supplies every value in it, and a
    literal written here would be a second source that can disagree.

    `compare=False` keeps a field out of `__eq__`, for the one field whose value
    identifies the run rather than configuring it - see `run_id`.
    """

    def factory():
        # The cached view, not `flat_config`: TrainConfig() reads ~90 fields and
        # the copying version re-flattened the whole file for each one. Only the
        # value taken is copied, so a list default is still its own object.
        values = flat_view(TRAIN_CONFIG_FILE)
        if key not in values:
            raise KeyError(
                f"{TRAIN_CONFIG_FILE} is missing the key {key!r}, which "
                f"TrainConfig has no default for. Keys found: {sorted(values)}."
            )
        return copy.deepcopy(values[key])

    return field(default_factory=factory, compare=compare)


@dataclass
class TrainConfig:
    """All training knobs in one place.

    This dataclass is the *schema*: it names every knob, its type, and what it
    does. It holds no values - each field's default is read from
    `config/train_config.json` by `_default`, so editing that file changes what
    a run does, with no second copy in Python to keep in step.
    """

    # --- Environment ---------------------------------------------------------
    num_agents: int = _default("num_agents")
    num_trained_agents: int = _default("num_trained_agents")
    init_cash: int = _default("init_cash")
    tick_size: int = _default("tick_size")
    mark_price_source: str = _default("mark_price_source")
    tape_display_length: int = _default("tape_display_length")
    max_step: int = _default("max_step")
    # "fixed" truncates every episode at max_step; "random" draws the horizon
    # per episode from [max_step_min, max_step_max] (docs/18 section 3.4).
    episode_length_mode: str = _default("episode_length_mode")
    max_step_min: int = _default("max_step_min")
    max_step_max: int = _default("max_step_max")
    is_render: bool = _default("is_render")
    n_hist: int = _default("n_hist")
    # How the public book is laid out in each snapshot: "grid" (fixed tick
    # offsets shared with the action's price code, S3-15) or "levels" (the
    # k_rows best occupied prices). A layout choice, recorded in the stamp.
    book_mode: str = _default("book_mode")
    # The observation's action mask says what each agent can do this step and
    # the modules refuse the rest; False emits all ones (docs/06 section 7).
    action_mask: bool = _default("action_mask")
    # The matching regime (docs/06 section 8): how a price level is shared out
    # ("fifo" / "pro_rata") and whether a step's crossing orders clear on
    # arrival or at one uniform price ("sequential" / "batch").
    matching_rule: str = _default("matching_rule")
    step_clearing: str = _default("step_clearing")
    # Whether a trader may rest several orders at one price (docs/15 S3-10).
    allow_multiple_orders_per_level: bool = _default("allow_multiple_orders_per_level")
    # What happens when equity runs out (docs/04 section 8): "market_adl"
    # closes a trader out below maintenance_margin - book first, then ADL for
    # the remainder, "gradual_adl" the same spread over up to
    # liquidation_horizon steps - and "off" leaves a bankrupt trader holding its position.
    liquidation: str = _default("liquidation")
    maintenance_margin: float = _default("maintenance_margin")
    # "gradual_adl" only: the most steps a close-out may take before ADL
    # takes the remainder.
    liquidation_horizon: int = _default("liquidation_horizon")
    # Exchange fees in basis points of a fill's notional (docs/04 section 9): the
    # taker pays taker_fee_bps, the maker maker_fee_bps (negative is a rebate).
    # Both 0 by default.
    maker_fee_bps: float = _default("maker_fee_bps")
    taker_fee_bps: float = _default("taker_fee_bps")

    # Bounds of the per-episode price anchor, drawn as randint(min, max) in
    # reset(). These were readable by the env but had no TrainConfig field, so
    # training runs could not narrow the range - the relative tick therefore
    # varied 10x across episodes with no way to control it. See docs/15 S3-4.
    initial_price_min: int = _default("initial_price_min")
    initial_price_max: int = _default("initial_price_max")

    # Order sizing. limit orders may be limit_size_multiple x larger than
    # market orders.
    min_size: int = _default("min_size")
    mkt_max_size: int = _default("mkt_max_size")
    limit_size_multiple: int = _default("limit_size_multiple")
    position_scale: int = _default("position_scale")

    # Reward coefficients. Previously hardcoded in Reward_Helper.set_reward,
    # which made them the least reachable knobs in the project despite being
    # the ones most worth sweeping.
    order_penalty: float = _default("order_penalty")
    trade_penalty: float = _default("trade_penalty")
    drawdown_penalty: float = _default("drawdown_penalty")
    passive_bonus: float = _default("passive_bonus")
    loss_multiplier: float = _default("loss_multiplier")
    # Per dead order-management action. Ships at 0.0; see the config note.
    dead_action_penalty: float = _default("dead_action_penalty")

    # --- Rollouts ------------------------------------------------------------
    # 0 keeps sampling in the driver process, which is the right setting for a
    # CPU dev box and for tests. Raise it for real training runs.
    num_env_runners: int = _default("num_env_runners")
    num_envs_per_env_runner: int = _default("num_envs_per_env_runner")
    num_cpus_per_env_runner: float = _default("num_cpus_per_env_runner")
    # How long the driver waits for a remote runner's share of the batch.
    # RLlib's default is 60s, which this env cannot meet at the configured
    # batch size: a timed-out iteration discards its partial rollouts, so the
    # learner gets nothing and the iteration trains on no data at all while
    # still counting itself and checkpointing. See the note in
    # train_config.json. Ignored when num_env_runners is 0.
    sample_timeout_s: float = _default("sample_timeout_s")

    # --- Learner -------------------------------------------------------------
    num_learners: int = _default("num_learners")
    # Fraction of a GPU per learner. Ignored (forced to 0) when CUDA is not
    # available, so a non-zero value here does not hard-fail a CPU-only machine.
    num_gpus_per_learner: float = _default("num_gpus_per_learner")

    # --- PPO -----------------------------------------------------------------
    num_episodes_per_iter: int = _default("num_episodes_per_iter")
    num_epochs: int = _default("num_epochs")
    lr: float = _default("lr")
    fcnet_hiddens: List[int] = _default("fcnet_hiddens")
    fcnet_activation: str = _default("fcnet_activation")
    # False keeps policy and value on separate trunks, which matters against
    # the non-stationary league opponents - see model_handler.
    vf_share_layers: bool = _default("vf_share_layers")
    # PPO requires minibatch_size <= train_batch_size_per_learner. RLlib's
    # default is 128, which is larger than the batch of a short-episode test
    # run, so this is exposed rather than left implicit.
    minibatch_size: Optional[int] = _default("minibatch_size")
    # The PPO entropy bonus, falling linearly from `entropy_coeff` to
    # `entropy_coeff_final` over `entropy_decay_iters` iterations (docs/15
    # S3-11). RLlib's own default is 0.0.
    # The discount and the GAE parameter (docs/15 S3-13). RLlib's own defaults are
    # 0.99 and 1.0.
    gamma: float = _default("gamma")
    lambda_: float = _default("lambda_")
    entropy_coeff: float = _default("entropy_coeff")
    entropy_coeff_final: float = _default("entropy_coeff_final")
    entropy_decay_iters: int = _default("entropy_decay_iters")

    # --- Optimiser -----------------------------------------------------------
    # Both default to torch's own values, so a run that changes neither builds
    # exactly the optimiser RLlib has always built. Set them to reproduce the
    # continual-backprop papers' RL recipe, which runs every algorithm but the
    # standard-PPO baseline at beta_1 = beta_2 = 0.99 and pairs CBP with a
    # weight decay of 1e-4. Kept apart from the CBP knobs on purpose: turning
    # both on at once would measure them together.
    adam_betas: List[float] = _default("adam_betas")
    adam_weight_decay: float = _default("adam_weight_decay")

    # --- Continual Backprop --------------------------------------------------
    # Selective reinitialisation of low-utility hidden units, after the
    # optimiser step. An update rule rather than an architecture, so it is
    # composed over whichever Learner the encoder chose instead of replacing
    # it - see train/model/cbp_learner.py.
    #
    # None of these is a STRUCTURAL_CONFIG_KEY: no tensor shape depends on
    # them, so unlike encoder_spec a restore may turn continual backprop on or
    # change its rate. The per-unit utility and ages are checkpoint state and
    # travel with the learner.
    cbp_enabled: bool = _default("cbp_enabled")
    cbp_metrics_only: bool = _default("cbp_metrics_only")
    # Counted in OPTIMISER STEPS, not iterations. See the cadence note in
    # train_config.json: this repo takes 4 Adam steps per iteration against the
    # papers' 320, so their values do not transfer.
    cbp_replacement_rate: float = _default("cbp_replacement_rate")
    cbp_maturity_threshold: int = _default("cbp_maturity_threshold")
    cbp_utility_decay: float = _default("cbp_utility_decay")
    cbp_utility: str = _default("cbp_utility")
    cbp_scope: str = _default("cbp_scope")
    cbp_fire_on: str = _default("cbp_fire_on")
    cbp_reset_optimizer_state: bool = _default("cbp_reset_optimizer_state")
    cbp_compensate_mean: bool = _default("cbp_compensate_mean")
    cbp_dead_unit_threshold: float = _default("cbp_dead_unit_threshold")
    cbp_metrics_every_n_updates: int = _default("cbp_metrics_every_n_updates")

    # --- Encoder -------------------------------------------------------------
    # Which network the trainable modules encode observations with. "mlp" is a
    # pass-through to the stock RLlib path built from fcnet_* above; any other
    # value routes them through CDACatalog. See train/model/encoders/.
    # Both are STRUCTURAL_CONFIG_KEYS - a restore cannot change them.
    encoder_type: str = _default("encoder_type")
    encoder_specs: Dict[str, Any] = _default("encoder_specs")
    # A `train.pretrain` checkpoint the trainable modules start from, or null
    # for a fresh initialisation. The checkpoint's encoder fingerprint is
    # checked against `encoder_type` / `encoder_specs` when the spec is built,
    # so a mismatch fails there rather than as a shape error inside RLlib.
    #
    # Deliberately NOT a structural key. It changes where the weights *start*,
    # not what shape they are, so resuming a run that used one is fine - the
    # checkpoint being restored already contains whatever the pretraining
    # contributed.
    pretrained_encoder_path: Optional[str] = _default("pretrained_encoder_path")

    # --- League self-play ----------------------------------------------------
    std_dev_multiplier: float = _default("std_dev_multiplier")
    max_champions: int = _default("max_champions")
    min_iterations_between_champions: int = _default("min_iterations_between_champions")
    # Mean trades per episode a trainable policy needs over the iteration to be
    # promoted (docs/15 S3-11). 0 disables the guard.
    min_champion_trades: float = _default("min_champion_trades")
    # Which modules the promotion threshold is computed over (docs/15 S3-12):
    # "pooled" or "excluding_baselines".
    promotion_reference: str = _default("promotion_reference")
    # Steps ahead at which fills are marked out (docs/15 S3-9).
    markout_horizons: List[int] = _default("markout_horizons")
    original_opponent_weight: float = _default("original_opponent_weight")
    champion_weight: float = _default("champion_weight")
    # null disables the per-step episode record entirely. See episode_data_path
    # for how this is resolved before it reaches the callback.
    episode_data_dir: Optional[str] = _default("episode_data_dir")
    # Record one episode in N. The record is ~34MB per 4096-step episode, so
    # "on" used to mean "until the disk fills"; this and episode_max_bytes are
    # what bound it (docs/21 §6 item 6).
    episode_sample_every: int = _default("episode_sample_every")
    episode_max_bytes: int = _default("episode_max_bytes")
    episode_rows_per_file: int = _default("episode_rows_per_file")
    episode_max_live_episodes: int = _default("episode_max_live_episodes")
    # Episode-end NAV conservation check. The ledger is Decimal throughout, so
    # the sum of every agent's NAV equals the cash the system started with, to
    # the cent; the tolerance only absorbs the float() round trip through the
    # info dict. strict raises on a violation rather than logging one, because
    # a broken conservation invariant means the ledger is corrupt and whatever
    # trains after it is meaningless.
    nav_tolerance: float = _default("nav_tolerance")
    strict_nav_check: bool = _default("strict_nav_check")

    # --- Run / checkpointing -------------------------------------------------
    # num_iters is a *target* iteration, not an amount: a restored run trains up
    # to it, so resuming a 16-iteration run at 9 does 7 more. That keeps the
    # total length of a run independent of how many times it was interrupted.
    # num_iters_is_delta restores the old reading - run num_iters more from
    # wherever the restore landed - for anyone who wants to extend a finished run.
    num_iters: int = _default("num_iters")
    num_iters_is_delta: bool = _default("num_iters_is_delta")
    chkpt_freq: int = _default("chkpt_freq")
    # How many `iter_*` checkpoints to retain. Every save used to overwrite one
    # directory, so a run had exactly one recoverable state and no way back from
    # a league that collapsed. <= 0 keeps all of them.
    chkpt_keep: int = _default("chkpt_keep")
    log_base_dir: str = _default("log_base_dir")
    # Names the per-run directory under log_base_dir holding progress.jsonl and
    # the run logs. null generates one, so two runs cannot land on the same
    # files: sharing run.log is the cross-process RotatingFileHandler race the
    # per-worker files already avoid for env runners, and sharing
    # progress.jsonl lets two drivers interleave writes inside one JSON line
    # (`json.dump` writes incrementally, and a result dict above the ~8KiB
    # stream buffer is several write syscalls). Pin it to resume into an
    # existing run directory. `__post_init__` resolves null to a real value, so
    # this is a str by the time anything reads it.
    #
    # Out of __eq__: it names the run, it does not configure it, and since
    # __post_init__ generates a fresh one per instance, comparing it would make
    # no two TrainConfigs equal - including the checked-in file against its own
    # defaults, and a restored checkpoint's config against the current one,
    # which `config_divergence` reports on.
    run_id: Optional[str] = _default("run_id", compare=False)
    is_restore: bool = _default("is_restore")
    # Which checkpoint to resume from. null takes the newest readable one under
    # checkpoint_dir, which is what a disconnect wants; a path pins one, which
    # is how a run is rolled back past a collapsed league. Requires is_restore.
    restore_path: Optional[str] = _default("restore_path")
    # Ray's log level, handed to PPOConfig.debugging.
    log_level: str = _default("log_level")
    # How Ray formats its own logging, in the driver and in every process it
    # starts for this job: "TEXT" or "JSON". Handed to `ray.LoggingConfig`,
    # which is the only lever that reaches a worker's Ray-side output at all -
    # including the traceback RLlib swallows when an env runner dies (docs/21
    # §2.1, §6 item 7). "" leaves Ray's logging alone.
    ray_log_encoding: str = _default("ray_log_encoding")
    # This package's own log level, applied by logging_setup and exported so
    # remote env runners - separate processes that never run main() - come up
    # at the same level. Kept apart from Ray's: Ray at INFO is noise, while
    # this package at INFO is the per-episode NAV table and the per-iteration
    # league statistics.
    cda_log_level: str = _default("cda_log_level")
    seed: Optional[int] = _default("seed")

    def __post_init__(self) -> None:
        """Resolve `run_id` once, here, rather than on each property read.

        A property that generated a name per call would hand a different
        directory to every caller, and `dataclasses.replace` - which the
        runtime profiles and the tests both use - would silently re-roll it.
        Resolving in the constructor makes the name a property of the config
        object, so a replace()d copy keeps writing where the original did.

        Also the boundary at which `encoder_type` stops being a config value
        and becomes an argument. Everything downstream takes it as a parameter
        and so only checks that it names something buildable; the config rules
        - no test fixtures - are enforced once, here, where the value arrives
        from a file.
        """
        if not self.run_id:
            self.run_id = generate_run_id()

        validate_encoder_type(self.encoder_type)

        if not 0.0 < self.gamma <= 1.0:
            raise ValueError(f"gamma must be in (0, 1]; got {self.gamma}.")
        if not 0.0 <= self.lambda_ <= 1.0:
            raise ValueError(f"lambda_ must be in [0, 1]; got {self.lambda_}.")
        if self.entropy_coeff < 0 or self.entropy_coeff_final < 0:
            raise ValueError(
                f"entropy_coeff and entropy_coeff_final must be >= 0; got "
                f"{self.entropy_coeff} and {self.entropy_coeff_final}."
            )
        if self.entropy_decay_iters < 1:
            raise ValueError(f"entropy_decay_iters must be >= 1; got {self.entropy_decay_iters}.")
        if self.promotion_reference not in PROMOTION_REFERENCES:
            raise ValueError(
                f"promotion_reference must be one of {PROMOTION_REFERENCES}; "
                f"got {self.promotion_reference!r}."
            )
        if any(int(h) < 1 for h in self.markout_horizons):
            raise ValueError(
                f"markout_horizons must be positive step counts; got {self.markout_horizons}."
            )
        if self.min_champion_trades < 0:
            raise ValueError(f"min_champion_trades must be >= 0; got {self.min_champion_trades}.")
        learners = max(int(self.num_learners), 1)
        if self.train_batch_size % learners:
            # RLlib takes the batch per learner and samples that times num_learners per
            # iteration (#299), so the iteration's batch has to split evenly across them.
            # The keys named are the ones that set the expected length in this mode (#304).
            length_keys = (
                "(max_step_min + max_step_max) // 2"
                if self.episode_length_mode == "random"
                else "max_step"
            )
            raise ValueError(
                f"train_batch_size {self.train_batch_size} (expected episode length x "
                f"num_episodes_per_iter) does not split evenly across num_learners="
                f"{self.num_learners}. Choose {length_keys} and num_episodes_per_iter so "
                "their product is a multiple of num_learners."
            )
        if self.cbp_enabled and self.num_learners > 1:
            # Replacements are chosen from each learner's own minibatch and applied outside the
            # gradient, so the replicas can pick different units and drift apart; nothing in
            # DDP pulls them back (docs/15 R-12, #182). `cbp_metrics_only` replaces nothing.
            raise ValueError(
                f"cbp_enabled with num_learners={self.num_learners}: continual backprop picks "
                "the unit to replace separately on each learner, so the replicas would diverge. "
                "Use num_learners 0 or 1, or cbp_metrics_only, until the choice is synchronised."
            )

    @property
    def entropy_setting(self):
        """What `PPOConfig.training(entropy_coeff=...)` takes: a float, or a schedule.

        A constant when the start and the end agree, so a run that sets both to
        0 builds exactly the config it did before. Otherwise RLlib's
        `[[env_step, value], ...]` form, with the end placed `entropy_decay_iters`
        iterations in; RLlib holds the last value after that.
        """
        if self.entropy_coeff == self.entropy_coeff_final:
            return float(self.entropy_coeff)
        return [
            [0, float(self.entropy_coeff)],
            [self.train_batch_size * self.entropy_decay_iters, float(self.entropy_coeff_final)],
        ]

    @classmethod
    def from_json(cls, path: str) -> "TrainConfig":
        """Build a TrainConfig from an arbitrary JSON file.

        `config/train_config.json` is already the source of every default, so
        this is for running against a *different* file - a sweep variant, or a
        config saved alongside a past run. Keys the other file omits fall back
        to the checked-in one.

        The file is grouped (`environment`, `rollouts`, `ppo`, ...) while this
        dataclass is flat, so groups are flattened one level. Keys beginning
        with `_` are documentation (`_source`, `_description`, `_note`) and are
        skipped at every level.

        Unknown keys raise rather than being ignored. Silently dropping a
        renamed or misspelled key is the failure mode this loader exists to
        remove.

        Note the one name change across the boundary: the field here is
        `num_agents`, and `env_config` forwards it to the env as
        `num_of_agents`.
        """
        with open(path) as fh:
            raw = json.load(fh)

        values = flatten(raw, path)

        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"{path}: unknown config keys {unknown}. Valid keys: {sorted(known)}")
        return cls(**values)

    @property
    def train_batch_size(self) -> int:
        """Timesteps per iteration: `num_episodes_per_iter` episodes' worth.

        Under a random horizon an episode's length is a draw, so the batch is
        sized by the mean of the range - the number of episodes it holds is
        then `num_episodes_per_iter` on average rather than exactly.

        This is the whole iteration, across every learner. RLlib is given
        `train_batch_size_per_learner` and samples that times `num_learners`
        (#299); the entropy schedule counts in the same env steps.
        """
        return self.expected_episode_length * self.num_episodes_per_iter

    @property
    def train_batch_size_per_learner(self) -> int:
        """Each learner's share of `train_batch_size`; all of it with 0 or 1 learner.

        `__post_init__` refuses a batch that does not split evenly, so the shares
        add back up to exactly `train_batch_size`.
        """
        return self.train_batch_size // max(int(self.num_learners), 1)

    @property
    def expected_episode_length(self) -> int:
        if self.episode_length_mode == "random":
            return (self.max_step_min + self.max_step_max) // 2
        return self.max_step

    @property
    def checkpoint_dir(self) -> str:
        """Root of the checkpoint tree. Individual saves are `iter_*` beneath it.

        Under `log_base_dir` and *not* under `run_dir`, which is the one place
        the per-run split is deliberately not applied. Restoring from a
        disconnect means finding the newest `iter_*` written by an *earlier*
        run; a per-run checkpoint tree would hide it, and every resumed run
        would start from scratch. Checkpoints are therefore shared across runs
        and the files that cannot tolerate sharing are not.

        `warn_about_stale_checkpoints` covers the cost of that sharing: a fresh
        run into a directory that already holds checkpoints says so.
        """
        return os.path.abspath(os.path.join(self.log_base_dir, "chkpt"))

    @property
    def run_dir(self) -> str:
        """This run's own directory, holding progress.jsonl and the run logs.

        Scoped per run rather than shared, because both files are written
        without any cross-process interlock: two drivers sharing one
        `log_base_dir` would rotate the same `run.log` underneath each other,
        and interleave partial writes into the same `progress.jsonl` line.
        Giving each run its own directory removes the sharing rather than
        trying to make the writes atomic.

        The checkpoint tree deliberately stays *outside* it - see
        `checkpoint_dir`.
        """
        return os.path.abspath(os.path.join(self.log_base_dir, self.run_id))

    @property
    def progress_path(self) -> str:
        """The per-iteration JSONL log, in this run's own directory.

        Under `log_base_dir` rather than `episode_data_dir` deliberately: this
        is one short line per iteration, so it belongs with the checkpoints that
        must survive a disconnect, not with the per-step episode record that
        runtime_profiles.json keeps off the Drive FUSE layer.

        Appending still matters within a run directory: the file is opened per
        iteration, so a killed run keeps what it had finished, and a restore
        that pins the same `run_id` extends that history rather than starting a
        second file.
        """
        return os.path.abspath(os.path.join(self.run_dir, PROGRESS_FILE))

    @property
    def episode_data_path(self) -> Optional[str]:
        """Where this run's per-step episode record goes, or None if it is off.

        Two things this does that the raw `episode_data_dir` did not, and both
        are the reasons docs/21 §2.3 called it the one output path with no
        protection at all:

        * **Absolute.** The callback carrying this string is pickled into every
          env runner, and `os.makedirs`/`open` in a worker resolve a relative
          path against whatever working directory that worker inherited. Today
          that is usually the driver's, because nothing sets a `runtime_env`
          `working_dir` - an accident, not a guarantee, and one that scatters
          the record silently rather than failing. The run log was given
          `abspath` for exactly this reason; this had been left behind.
        * **Run-scoped.** `run_id` beneath it, so two concurrent runs cannot
          write into one directory. The same argument as `run_dir` (§1.11): the
          files carry no interlock, so the answer is not to share them.

        Deliberately *not* under `run_dir`: `runtime_profiles.json` splits
        `results_root` from `episode_data_root` precisely so this can be kept
        off a Drive FUSE mount while the checkpoints stay on it.
        """
        if self.episode_data_dir is None:
            return None
        return os.path.abspath(os.path.join(self.episode_data_dir, self.run_id))

    #: Env config keys whose `TrainConfig` field has another name.
    _ENV_KEY_FIELDS = {"num_of_agents": "num_agents"}

    @property
    def env_config(self) -> dict:
        """The env's config dict, one entry per `EnvSettings` key (issue #257).

        Generated from the settings' field list, so a key added there and given a
        `TrainConfig` field of the same name (or an entry in `_ENV_KEY_FIELDS`) reaches
        the env without a third place to write it out.
        """
        return {
            key: getattr(self, self._ENV_KEY_FIELDS.get(key, key)) for key in EnvSettings.keys()
        }

    def resolved_gpus_per_learner(self) -> float:
        """num_gpus_per_learner, forced to 0 when no CUDA device is present."""
        if self.num_gpus_per_learner and not torch.cuda.is_available():
            logger.warning(
                "num_gpus_per_learner=%s requested but torch.cuda.is_available() "
                "is False - falling back to CPU.",
                self.num_gpus_per_learner,
            )
            return 0.0
        return self.num_gpus_per_learner
