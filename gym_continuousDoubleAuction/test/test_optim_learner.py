"""`adam_settings`: the one reader of the `optimizer` group.

`TunedAdamMixin` builds torch's Adam from it, and the cda-cbp extension builds
the authors' `AdamGnT` from it, so the two optimisers read the same settings
from the same place rather than each parsing the group.
"""

from gym_continuousDoubleAuction.train.model.optim_learner import (
    OPTIMIZER_CONFIG_KEY,
    adam_settings,
)


def _lcd(**values):
    return {OPTIMIZER_CONFIG_KEY: values}


class TestAdamSettings:
    def test_nothing_configured_is_empty(self):
        """Empty means the optimiser's own defaults, exactly as RLlib builds it."""
        assert adam_settings(None) == {}
        assert adam_settings({}) == {}
        assert adam_settings(_lcd(adam_betas=None, adam_weight_decay=0.0)) == {}

    def test_only_what_is_set_is_passed(self):
        assert adam_settings(_lcd(adam_weight_decay=1e-4)) == {"weight_decay": 1e-4}
        assert adam_settings(_lcd(adam_betas=[0.99, 0.99])) == {"betas": (0.99, 0.99)}

    def test_both(self):
        settings = adam_settings(_lcd(adam_betas=[0.99, 0.99], adam_weight_decay=1e-4))
        assert settings == {"betas": (0.99, 0.99), "weight_decay": 1e-4}

    def test_a_json_list_becomes_the_tuple_torch_expects(self):
        assert isinstance(adam_settings(_lcd(adam_betas=[0.9, 0.999]))["betas"], tuple)
