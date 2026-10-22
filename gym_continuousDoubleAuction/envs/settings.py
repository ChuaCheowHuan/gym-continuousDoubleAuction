"""The environment's configuration, read and checked in one place (issue #257).

`continuousDoubleAuctionEnv.__init__` used to read thirty-odd keys one at a time with
`self._cfg(...)`, validate some of them inline, and forward them through the mixin chain
as a long keyword list; `TrainConfig.env_config` then wrote the same keys out a third
time. Here the keys are the fields of one frozen dataclass, built by one function that
names the key in every error:

    settings = EnvSettings.from_config(config)    # config key, else config/env_defaults.json
    settings.as_config()                          # the same keys back, for `env_config`
    settings.helper_kwargs()                      # what the mixin chain takes

Adding a config key means a field here, the JSON, and the `TrainConfig` field it comes
from; `test_refactors.py` holds `EnvSettings` to `env_defaults.json` key for key.

No value is written here: a key the caller omits is read from `config/env_defaults.json`,
and a key that file lacks raises from the loader.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, Mapping

from ..config_loader import env_default
from .account.account import validate_fee_rates


@dataclass(frozen=True)
class EnvSettings:
    """One field per `config/env_defaults.json` key, in the order `env_config` lists them."""

    num_of_agents: int
    init_cash: Any
    tick_size: Any
    mark_price_source: str
    tape_display_length: int
    max_step: int
    episode_length_mode: str
    max_step_min: int
    max_step_max: int
    is_render: bool
    n_hist: int
    book_mode: str
    action_mask: bool
    matching_rule: str
    step_clearing: str
    allow_multiple_orders_per_level: bool
    liquidation: str
    maintenance_margin: Any
    liquidation_horizon: int
    maker_fee_bps: Any
    taker_fee_bps: Any
    market_variety: Mapping[str, Any]
    initial_price_min: Any
    initial_price_max: Any
    min_size: int
    mkt_max_size: int
    limit_size_multiple: Any
    position_scale: Any
    order_penalty: Any
    trade_penalty: Any
    drawdown_penalty: Any
    passive_bonus: Any
    loss_multiplier: Any
    dead_action_penalty: Any

    #: Read by the env itself rather than forwarded to the exchange.
    ENV_ONLY = frozenset(
        {
            "num_of_agents",
            "is_render",
            "max_step",
            "episode_length_mode",
            "max_step_min",
            "max_step_max",
            "maker_fee_bps",
            "taker_fee_bps",
            "allow_multiple_orders_per_level",
            "market_variety",
        }
    )
    #: The keys `market_variety` may redraw at reset: each can change between
    #: episodes without changing the observation or action space.
    MARKET_VARIETY_KEYS = ("matching_rule", "step_clearing", "maker_fee_bps", "taker_fee_bps")
    #: The reward model's coefficients (`RewardModel`).
    REWARD_KEYS = (
        "order_penalty",
        "trade_penalty",
        "drawdown_penalty",
        "passive_bonus",
        "loss_multiplier",
        "dead_action_penalty",
    )
    #: The liquidation engine's settings (`LiquidationEngine`).
    LIQUIDATION_KEYS = ("liquidation", "maintenance_margin", "liquidation_horizon")

    def __post_init__(self) -> None:
        if self.num_of_agents < 1:
            raise ValueError(f"num_of_agents must be at least 1; got {self.num_of_agents!r}.")
        # Validated here so a bad schedule fails at construction, before the book is
        # built; `Account` validates again for callers that skip the env.
        validate_fee_rates(self.maker_fee_bps, self.taker_fee_bps)
        if not isinstance(self.allow_multiple_orders_per_level, bool):
            raise ValueError(
                f"allow_multiple_orders_per_level must be true or false; got "
                f"{self.allow_multiple_orders_per_level!r}."
            )
        self._check_market_variety()
        if self.episode_length_mode not in ("fixed", "random"):
            raise ValueError(
                f"episode_length_mode must be 'fixed' or 'random'; got "
                f"{self.episode_length_mode!r}."
            )
        if self.episode_length_mode == "random":
            if self.max_step_min < 1 or self.max_step_min > self.max_step_max:
                raise ValueError(
                    f"episode_length_mode 'random' needs 1 <= max_step_min <= "
                    f"max_step_max; got {self.max_step_min} and {self.max_step_max}."
                )
        elif self.max_step < 1:
            raise ValueError(
                f"episode_length_mode 'fixed' needs max_step >= 1; got {self.max_step!r}."
            )

    def _check_market_variety(self) -> None:
        """Refuse a `market_variety` that could draw a market the env would reject."""
        # Imported here: the exchange imports the env's components, not this module,
        # but keeping the import local keeps settings importable on its own.
        from .exchg.exchg_helper import Exchg_Helper
        from .orderbook.orderbook import OrderBook

        variety = self.market_variety
        if not isinstance(variety, Mapping):
            raise ValueError(
                f"market_variety must be a dict of lists (or {{}} for off); got {variety!r}."
            )
        unknown = sorted(set(variety) - set(self.MARKET_VARIETY_KEYS))
        if unknown:
            raise ValueError(
                f"market_variety may only name {list(self.MARKET_VARIETY_KEYS)}, which can "
                f"change between episodes without changing the spaces; got {unknown}."
            )
        allowed = {
            "matching_rule": OrderBook.MATCHING_RULES,
            "step_clearing": Exchg_Helper.STEP_CLEARINGS,
        }
        for key, values in variety.items():
            if not isinstance(values, list) or not values:
                raise ValueError(
                    f"market_variety[{key!r}] must be a non-empty list; got {values!r}."
                )
            if key in allowed and not set(values) <= set(allowed[key]):
                raise ValueError(
                    f"market_variety[{key!r}] may only hold {list(allowed[key])}; got {values!r}."
                )
        makers = variety.get("maker_fee_bps", [self.maker_fee_bps])
        takers = variety.get("taker_fee_bps", [self.taker_fee_bps])
        for maker in makers:
            for taker in takers:
                validate_fee_rates(maker, taker)

    @classmethod
    def keys(cls) -> tuple:
        """The config keys, in order."""
        return tuple(f.name for f in fields(cls))

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "EnvSettings":
        """Every key from `config`, else from `config/env_defaults.json`; validated."""
        values = {key: config[key] if key in config else env_default(key) for key in cls.keys()}
        # The horizon bounds are integers whatever a JSON or CLI source handed over.
        values["max_step_min"] = int(values["max_step_min"])
        values["max_step_max"] = int(values["max_step_max"])
        return cls(**values)

    @property
    def time_left_horizon(self) -> int:
        """The latest possible end of an episode, which is the horizon the agent is shown."""
        return self.max_step_max if self.episode_length_mode == "random" else self.max_step

    def as_config(self) -> Dict[str, Any]:
        """All keys as an env config dict (what `TrainConfig.env_config` hands to the env)."""
        return {key: getattr(self, key) for key in self.keys()}

    def reward_kwargs(self) -> Dict[str, Any]:
        """The keys `RewardModel` takes."""
        return {key: getattr(self, key) for key in self.REWARD_KEYS}

    def helper_kwargs(self) -> Dict[str, Any]:
        """The keys the exchange (with its state and action mixins) and its components take.

        The reward coefficients are left out: `reward_kwargs` builds the model that holds them.
        """
        return {
            key: getattr(self, key)
            for key in self.keys()
            if key not in self.ENV_ONLY and key not in self.REWARD_KEYS
        }
