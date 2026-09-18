"""The action mask: what is impossible is never chosen; what is unwise is learnt.

doc/06 section 6. The env writes nine floats into each agent's private block -
one per action category, 1.0 where the category is possible on the coming
step - and the modules honour them: the PPO module adds a large negative
number to a masked category's logit, the random baseline redraws a masked
category among the possible ones. Two impossibilities are masked, both exact:
a modify or cancel with nothing of the agent's resting on that side (the
"unmatched" dead action, 27-30% of random agent-steps before this), and a
market or limit order the cash check would refuse for the minimum size at the
reference price (the "rejected" dead action). Pass is always possible. With
`action_mask` off the env emits all ones, so the layout is one and the
unmasked baseline is a config flag.
"""
import numpy as np
import torch
from ray.rllib.core.columns import Columns
from ray.rllib.core.rl_module.rl_module import RLModuleSpec

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.action_helper import _CATEGORY_MAP
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    ACTION_MASK_OFFSET,
    MASK_FIELDS,
    PRIVATE_FIELDS,
    action_mask_offset,
)
from gym_continuousDoubleAuction.train.model.action_mask import (
    MASK_LOGIT,
    category_logit_slice,
    mask_slice,
    masked_logits,
)
from gym_continuousDoubleAuction.train.model.model_handler import (
    RandomRLModule,
    build_trainable_module_spec,
)


def _env(**overrides):
    config = {"num_of_agents": 2, "is_render": False, "max_step": 40,
              "initial_price_min": 100, "initial_price_max": 100}
    config.update(overrides)
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _pass(env):
    return {agent: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                    "size_mean": np.zeros(1, dtype=np.float32),
                    "size_sigma": np.zeros(1, dtype=np.float32)}
            for agent in env.agents}


def _mask(env, obs, agent="agent_0"):
    return dict(zip(MASK_FIELDS, obs[agent][-len(MASK_FIELDS):]))


class TestLayout:

    def test_the_mask_closes_the_private_block(self):
        assert PRIVATE_FIELDS[-9:] == MASK_FIELDS
        assert ACTION_MASK_OFFSET == len(PRIVATE_FIELDS) - 9 == action_mask_offset(10)

    def test_mask_fields_follow_the_category_map(self):
        """Entry i describes category i - the order the head's logits use."""
        for category, (side, kind) in _CATEGORY_MAP.items():
            name = MASK_FIELDS[category]
            if side is None:
                assert name == "can_pass"
            else:
                assert name == f"can_{side}_{kind}"

    def test_slices_are_derived_from_the_spaces(self):
        env = _env()
        assert category_logit_slice(env.action_space) == slice(0, 9)
        sl = mask_slice(env.observation_space)
        assert sl == slice(env.observation_space.shape[0] - 9, env.observation_space.shape[0])

    def test_a_space_without_the_block_has_no_mask(self):
        import gymnasium as gym
        space = gym.spaces.Box(-1, 1, shape=(4 * 48 + 9,), dtype=np.float32)
        assert mask_slice(space) is None


class TestWhatIsMasked:

    def test_nothing_resting_masks_modify_and_cancel(self):
        env = _env()
        obs, _ = env.reset(seed=1)
        m = _mask(env, obs)
        assert m["can_pass"] == 1.0
        for name in ("can_bid_modify", "can_bid_cancel", "can_ask_modify", "can_ask_cancel"):
            assert m[name] == 0.0, name
        for name in ("can_bid_market", "can_bid_limit", "can_ask_market", "can_ask_limit"):
            assert m[name] == 1.0, name

    def test_a_resting_bid_unmasks_that_side_only(self):
        env = _env()
        a, _ = env.traders
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        obs, *_ = env.step(_pass(env))
        m = _mask(env, obs)
        assert m["can_bid_modify"] == 1.0 and m["can_bid_cancel"] == 1.0
        assert m["can_ask_modify"] == 0.0 and m["can_ask_cancel"] == 0.0
        # agent_1 has nothing resting: everything order-management is masked.
        m1 = _mask(env, obs, "agent_1")
        assert m1["can_bid_cancel"] == 0.0 and m1["can_ask_cancel"] == 0.0

    def test_no_cash_masks_opening_orders(self):
        """A trader that cannot afford one contract at the reference cannot
        open; it can still pass, and still close if it holds a position."""
        env = _env()
        a, b = env.traders
        env.last_price = 100.0
        a.acc.cash = a.acc.cash.__class__(0)   # Decimal(0)
        obs, *_ = env.step(_pass(env))
        m = _mask(env, obs)
        assert m["can_pass"] == 1.0
        assert m["can_bid_market"] == 0.0 and m["can_bid_limit"] == 0.0
        assert m["can_ask_market"] == 0.0 and m["can_ask_limit"] == 0.0
        # agent_1, funded, can open either way.
        m1 = _mask(env, obs, "agent_1")
        assert m1["can_bid_limit"] == 1.0 and m1["can_ask_limit"] == 1.0

    def test_a_position_can_be_closed_without_cash(self):
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 100.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 100.0, env.LOB, env.traders)   # a is long 10
        a.acc.cash = a.acc.cash.__class__(0)
        obs, *_ = env.step(_pass(env))
        m = _mask(env, obs)
        assert a.acc.net_position == 10
        assert m["can_ask_limit"] == 1.0 and m["can_ask_market"] == 1.0  # closing
        assert m["can_bid_limit"] == 0.0                                  # opening

    def test_the_mask_agrees_with_the_cash_check(self):
        """Random play: every step, a category the mask allows for a limit
        order at the reference and minimum size is one `_order_approved`
        would approve, and one it masks is one it would refuse."""
        env = _env(num_of_agents=4, init_cash=2000, max_step=60)
        for _ in range(60):
            obs, _, dones, truncs, _ = env.step(
                {agent: env.action_spaces[agent].sample() for agent in env.agents}
            )
            R = env.reference_price()
            for trader in env.traders:
                if trader.acc.nav <= 0:
                    continue
                m = _mask(env, obs, f"agent_{trader.ID}")
                for side in ("bid", "ask"):
                    ok = trader._order_approved(side, env.min_size, R, env.LOB, "limit")
                    assert m[f"can_{side}_limit"] == float(ok), (side, m)
            if dones["__all__"] or truncs["__all__"]:
                break

    def test_disabled_emits_all_ones(self):
        env = _env(action_mask=False)
        obs, _ = env.reset(seed=1)
        assert all(v == 1.0 for v in _mask(env, obs).values())
        assert env.private_dim == 41  # same layout either way


class TestModulesHonourIt:

    def _module(self, env):
        return build_trainable_module_spec(env.observation_space, env.action_space,
                                           encoder_type="mlp").build()

    def test_masked_categories_get_the_penalty(self):
        env = _env()
        obs, _ = env.reset(seed=1)
        module = self._module(env)
        o = torch.as_tensor(np.stack([obs["agent_0"]]), dtype=torch.float32)
        for forward in (module._forward, module._forward_train):
            logits = forward({Columns.OBS: o})[Columns.ACTION_DIST_INPUTS][0, :9]
            masked = [3, 4, 7, 8]
            assert all(float(logits[i]) < MASK_LOGIT / 2 for i in masked)
            assert all(abs(float(logits[i])) < 1e3 for i in range(9) if i not in masked)

    def test_sampling_never_draws_a_masked_category(self):
        env = _env()
        obs, _ = env.reset(seed=1)
        module = self._module(env)
        o = torch.as_tensor(np.stack([obs["agent_0"]] * 64), dtype=torch.float32)
        out = module._forward({Columns.OBS: o})
        dist = module.get_inference_action_dist_cls().from_logits(out[Columns.ACTION_DIST_INPUTS])
        cats = dist.sample()["category"].numpy()
        assert set(cats.tolist()) <= {0, 1, 2, 5, 6}

    def test_masked_logits_is_out_of_place_and_leaves_other_heads_alone(self):
        logits = torch.zeros(2, 31)
        obs = torch.ones(2, 233)
        obs[0, 224 + 3] = 0.0
        out = masked_logits(logits, obs, slice(224, 233), slice(0, 9))
        assert float(out[0, 3]) == MASK_LOGIT and float(out[1, 3]) == 0.0
        assert torch.all(out[:, 9:] == 0) and torch.all(logits == 0)

    def test_the_random_baseline_redraws_masked_categories(self):
        env = _env()
        obs, _ = env.reset(seed=1)
        rnd = RLModuleSpec(module_class=RandomRLModule, observation_space=env.observation_space,
                           action_space=env.action_space).build()
        rnd.action_space.seed(3)
        o = torch.as_tensor(np.stack([obs["agent_0"]] * 200), dtype=torch.float32)
        cats = rnd._forward({Columns.OBS: o})[Columns.ACTIONS]["category"]
        assert set(np.asarray(cats).tolist()) <= {0, 1, 2, 5, 6}
        assert len(set(np.asarray(cats).tolist())) >= 3

    def test_an_episode_of_masked_random_play_has_no_dead_actions(self):
        """The point: with the mask honoured, `num_unmatched_step` is 0 on
        every agent-step, where a fifth to a third used to be."""
        env = _env(num_of_agents=4, max_step=50)
        rnd = RLModuleSpec(module_class=RandomRLModule, observation_space=env.observation_space,
                           action_space=env.action_space).build()
        obs, _ = env.reset(seed=4)
        unmatched = 0
        while True:
            o = torch.as_tensor(np.stack([obs[a] for a in env.agents]), dtype=torch.float32)
            acts = rnd._forward({Columns.OBS: o})[Columns.ACTIONS]
            actions = {a: {k: (np.asarray(v[i]) if k in ("size_mean", "size_sigma") else int(v[i]))
                           for k, v in acts.items()} for i, a in enumerate(env.agents)}
            obs, _, dones, truncs, infos = env.step(actions)
            unmatched += sum(i["num_unmatched_step"] for i in infos.values())
            if dones["__all__"] or truncs["__all__"]:
                break
        assert unmatched == 0


def test_compare_can_switch_it():
    from gym_continuousDoubleAuction.train.compare import parse_overrides
    assert parse_overrides(["action_mask=false"]) == {"action_mask": False}
    assert parse_overrides(["action_mask=true"]) == {"action_mask": True}
