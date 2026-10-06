"""Every reward term the env reports is drawn, in a colour of its own.

`TERM_COLORS` was a five-tuple zipped against `REWARD_TERMS`, which grew a sixth
term (`dead_action_penalty`). `zip` stops at the shorter, so the decomposition
and the training means silently left the sixth term out - and the plotted terms
no longer summed to the total line beside them, which reads as an accounting
break. The variance-share stack got six series and five colours, so matplotlib
reused the first and drew the sixth term in `nav_term`'s blue.
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS  # noqa: E402

from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS  # noqa: E402
from gym_continuousDoubleAuction.visualize import visualize_training  # noqa: E402
from gym_continuousDoubleAuction.visualize.visualize_rewards import TERM_COLORS  # noqa: E402


def _rows():
    share = 1.0 / len(REWARD_TERMS)
    return [
        {"training_iteration": it, ENV_RUNNER_RESULTS: {
            **{f"reward_term_mean_{t}": -0.1 for t in REWARD_TERMS},
            **{f"reward_term_var_share_{t}": share for t in REWARD_TERMS},
        }}
        for it in (1, 2)
    ]


def test_every_term_has_a_colour_of_its_own():
    assert set(TERM_COLORS) == set(REWARD_TERMS)
    assert len(set(TERM_COLORS.values())) == len(REWARD_TERMS)


def test_the_means_panel_draws_every_term():
    fig, ax = plt.subplots()
    visualize_training._plot_reward_term_means(ax, _rows())
    assert sorted(line.get_label() for line in ax.get_lines() if line.get_label() in REWARD_TERMS) \
        == sorted(REWARD_TERMS)
    plt.close(fig)


def test_the_share_stack_gives_every_term_its_own_colour():
    fig, ax = plt.subplots()
    visualize_training._plot_reward_term_shares(ax, _rows())
    colours = [tuple(poly.get_facecolor()[0]) for poly in ax.collections]
    assert len(colours) == len(REWARD_TERMS)
    assert len(set(colours)) == len(REWARD_TERMS)
    plt.close(fig)
