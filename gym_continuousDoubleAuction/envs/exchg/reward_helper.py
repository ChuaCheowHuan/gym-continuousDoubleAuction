from ...config_loader import env_default

class Reward_Helper(object):

    def __init__(self, order_penalty=env_default("order_penalty"),
                 trade_penalty=env_default("trade_penalty"),
                 drawdown_penalty=env_default("drawdown_penalty"),
                 passive_bonus=env_default("passive_bonus"),
                 loss_multiplier=env_default("loss_multiplier"),
                 **kwargs):
        """
        Coefficients of the reward formula in `set_reward`.

        Every coefficient below multiplies a quantity already expressed as a
        FRACTION OF THE TRADER'S STARTING NAV - see `set_reward` - so they are
        all in units of "reward per unit of initial capital", and a value of
        1e-5 means one basis point of it. They were an order of magnitude
        apart from that before, which is finding S2-3.

        Arguments:
            order_penalty: Per order placed this step.
            trade_penalty: Per trade filled this step.
            drawdown_penalty: Per unit of *newly opened* drawdown, as a
                fraction of starting NAV. Charged on the signed change in the
                drawdown level, not on the level itself - see `set_reward`.
            passive_bonus: Per passive (liquidity-providing) fill this step.
            loss_multiplier: Extra weight on negative NAV changes. **1.0 is the
                only value that leaves the game zero-sum.** Total NAV is
                conserved exactly, so `sum(nav_change) == 0` across agents; any
                multiplier above 1 therefore makes `sum(reward) < 0`, which
                makes passing a dominant strategy for everyone and collapses
                the market. That is finding S1-3, and it is why this ships at
                1.0 rather than the 1.5 it had.

        Defaults come from `config/env_defaults.json`. A training run sets all
        five from `train_config.json` via `TrainConfig.env_config`.
        """
        self.order_penalty = order_penalty
        self.trade_penalty = trade_penalty
        self.drawdown_penalty = drawdown_penalty
        self.passive_bonus = passive_bonus
        self.loss_multiplier = loss_multiplier

        super().__init__(**kwargs)

    def set_reward(self, rewards, trader):
        """
        Calculate and set the reward for the trader at the current time step.

        The reward aligns with:
        1. Maximizing NAV (nav_change)
        2. Reducing number of trades (trade_penalty)
        3. Selective order placement (order_penalty)
        4. Lowering drawdown risk (drawdown_penalty & loss_multiplier)
        5. Capturing spread (passive_bonus)

        Args:
            rewards (dict): Dictionary to store rewards for each agent.
            trader (object): The trader object containing account information.

        Returns:
            dict: Updated rewards dictionary.
        """
        # Every NAV-derived quantity is divided by the trader's own starting
        # NAV, so the reward is in units of initial capital rather than in
        # dollars. That is finding S1-1: PPO clamps the value loss at
        # `vf_clip_param` (RLlib's default 10.0), while value targets built
        # from dollar NAV sums land in the 1e4-1e7 range. `clamp(vf_loss, 0,
        # 10)` is flat there, so the critic's gradient was exactly zero for
        # every sample and `vf_explained_var` sat at ~9e-05 - PPO degenerated
        # to REINFORCE with a batch-standardised baseline. It was silent
        # because `total_loss` looks small and stable when 10.0 of it is a
        # constant.
        #
        # `acc.init_nav` rather than the configured `init_cash`: the account
        # already records what this trader actually started with, so the scale
        # cannot drift from the ledger it normalises. A second copy of that
        # number is how S1-4 happened.
        scale = float(trader.acc.init_nav)
        if scale <= 0:
            raise ValueError(
                f"Trader {trader.ID} has init_nav={scale}, so the reward "
                "cannot be expressed as a fraction of starting capital. "
                "init_cash must be > 0 (see env_defaults.json)."
            )

        nav_change = float(trader.acc.nav - trader.acc.prev_nav) / scale

        # Penalties/Bonus coefficients, set from the env config (see __init__).
        order_penalty = self.order_penalty
        trade_penalty = self.trade_penalty
        drawdown_penalty = self.drawdown_penalty
        passive_bonus = self.passive_bonus
        loss_multiplier = self.loss_multiplier

        # 1. Asymmetric Loss Aversion: Penalize negative nav_change more heavily
        nav_term = nav_change * (loss_multiplier if nav_change < 0 else 1.0)

        # 2. Drawdown: the CHANGE in distance from peak NAV, not the distance.
        #
        # The level was charged on every one of an episode's 4,096 steps, so a
        # single early loss became a per-step tax for the rest of the episode
        # even from an agent that then did nothing, and the total scaled with
        # episode length. That is finding S2-1.
        #
        # The change is *signed*, which matters more than it looks. Clipping it
        # at zero - charging only newly opened drawdown - reads like the
        # cautious choice, but below the peak it charges `nav_term` a second
        # time on every losing step and never refunds it on the way back up: a
        # round trip would cost `drawdown_penalty * X`, which is an asymmetric
        # loss multiplier wearing a different hat and reintroduces exactly the
        # negative-sum bias that `loss_multiplier: 1.0` removes. Signed, the
        # per-step charges telescope: over an episode they sum to
        # `-drawdown_penalty * final_drawdown` regardless of the path taken to
        # get there, so a round trip is free, ending in drawdown is still
        # penalised, and no sequence of trades can farm the term - the sum is
        # bounded above by zero because drawdown itself is.
        previous_drawdown = float(trader.acc.drawdown)
        current_drawdown = float(max(0, trader.acc.max_nav - trader.acc.nav))
        drawdown_change = (current_drawdown - previous_drawdown) / scale

        # 3. Comprehensive Reward Formula
        #
        # Kept as the signed contribution of each term rather than a single
        # expression, so the decomposition doc/07 6.4 asks to monitor is the
        # same arithmetic the agent is actually trained on: accumulating the
        # terms *is* the reward, and there is no second expression that could
        # drift out of step with the logged split.
        terms = {
            "nav_term": nav_term,
            "order_penalty": -(order_penalty * trader.acc.order_step_placed),
            "trade_penalty": -(trade_penalty * trader.acc.num_trades_step),
            "drawdown_penalty": -(drawdown_penalty * drawdown_change),
            "passive_bonus": passive_bonus * trader.acc.num_passive_fills_step,
        }

        # Accumulated left to right, deliberately NOT with sum() or math.fsum().
        # Instrumenting the reward must not change it, and on Python 3.12+ the
        # builtin sum() applies Neumaier compensated summation to floats: it is
        # more accurate, and it disagrees with this loop on ~44% of random
        # inputs (~1e-13 relative). Insertion order matches the original
        # formula and `a - b` is `a + (-b)` exactly in IEEE 754, so this
        # reproduces the previous expression bit for bit. Iterating the dict
        # rather than naming the five keys also means a term added later cannot
        # be logged but left out of the reward.
        reward = 0.0
        for value in terms.values():
            reward += value

        rewards[f'agent_{trader.ID}'] = reward
        trader.acc.reward = reward
        trader.acc.reward_terms = terms
        # Load-bearing twice over, so do not move or fold this away. It is the
        # drawdown level doc/11 2.3 wanted recorded, AND it is what the *next*
        # step reads back as `previous_drawdown` to form its signed change.
        # Dropping it would silently turn the drawdown term back into the level
        # penalty S2-1 is about, since `previous_drawdown` would then be 0.0 on
        # every step and the "change" would equal the level.
        trader.acc.drawdown = current_drawdown

        return rewards