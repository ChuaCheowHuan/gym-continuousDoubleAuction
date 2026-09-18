"""`train.export` against a real checkpoint: train, promote, save, export.

`test_export.py` covers which module is chosen and what the record carries.
What only a real checkpoint can show is that the chosen module id resolves to a
directory RLlib will deserialise, and that the tensors written are the trained
ones rather than a fresh initialisation - the failure that looks like success,
because a randomly initialised network exports perfectly.
"""
import pytest
import ray
import torch

from gym_continuousDoubleAuction.train import export
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    trainable_policy_ids,
)
from gym_continuousDoubleAuction.train.probe import features as features_module
from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    algo_callback,
    build_config,
    save_checkpoint,
)

CFG = dict(
    num_agents=4, num_trained_agents=2, max_step=32, num_episodes_per_iter=2,
    num_epochs=1, minibatch_size=32, num_env_runners=0, num_learners=0,
    num_gpus_per_learner=0, episode_data_dir=None, log_level="ERROR",
)


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    """One trained iteration with a champion guaranteed to be in the league.

    The iteration may promote one of its own - with the shipped
    `std_dev_multiplier` of 0.1 it usually does - so one is forced with a
    return no organic promotion will beat, and that is the module the export is
    expected to choose.
    """
    ray.init(ignore_reinit_error=True, include_dashboard=False,
             log_to_driver=False, num_cpus=2)
    root = tmp_path_factory.mktemp("export")
    cfg = TrainConfig(log_base_dir=str(root), chkpt_keep=0, seed=0, **CFG)
    ppo, _ = build_config(cfg)
    algo = ppo.build_algo()
    algo.train()

    source = trainable_policy_ids(cfg.num_trained_agents)[0]
    callback = algo_callback(algo)
    callback._create_champion_snapshot_from_policy(
        algo, source, return_value=1e6, iteration=1,
    )
    forced = callback.champion_history[-1]["id"]
    path = save_checkpoint(algo, cfg, int(algo.iteration))
    algo.stop()
    yield path, forced, source
    ray.shutdown()


def test_the_default_is_the_best_champion(checkpoint, tmp_path):
    path, forced, _source = checkpoint
    record = export.export(path, out=str(tmp_path / "w.pt"))
    assert record["module_id"] == forced
    assert record["promotion"]["return"] == 1e6
    assert record["training_iteration"] == 1


def test_the_weights_are_the_source_policy_s_acting_weights(checkpoint, tmp_path):
    """A champion is a copy of its source, so the two must agree.

    Only the acting path: `_create_champion_snapshot_from_policy` copies the
    whole module state from the LearnerGroup, so the critic agrees too - but
    that is the mechanism under test elsewhere. What must hold here is that the
    file does not hold a fresh initialisation, and comparing against the source
    policy proves it against a network that was actually trained.
    """
    path, forced, source = checkpoint
    exported = export.export(path, out=str(tmp_path / "champ.pt"))["state_dict"]
    reference = features_module.load_module(path, source).state_dict()

    assert sorted(exported) == sorted(reference)
    mismatched = [
        key for key in exported
        if not torch.allclose(exported[key], reference[key].detach().cpu())
    ]
    assert mismatched == [], f"{forced} is not a copy of {source}: {mismatched}"


def test_a_named_module_is_exported_and_reloads(checkpoint, tmp_path):
    path, _forced, source = checkpoint
    out = tmp_path / "policy.pt"
    export.export(path, module_id=source, out=str(out))

    back = torch.load(out, weights_only=False)
    assert back["module_id"] == source
    assert back["promotion"] is None, "a trainable policy has no promotion record"
    assert back["layout"]["observation_version"] >= 1
    assert back["state_dict"], "no tensors written"
    live = features_module.load_module(path, source).state_dict()
    assert sorted(back["state_dict"]) == sorted(live)


def test_a_module_the_checkpoint_does_not_have_is_named(checkpoint, tmp_path):
    path, _forced, _source = checkpoint
    with pytest.raises(FileNotFoundError, match="policy_99"):
        export.export(path, module_id="policy_99", out=str(tmp_path / "x.pt"))


def test_list_names_every_module_and_the_champion(checkpoint):
    path, forced, source = checkpoint
    state = export.read_league_state(path)
    text = export.render(state, features_module.available_modules(path))
    assert source in text and forced in text
    assert "| yes |" in text


def test_the_cli_writes_a_file_and_exits_zero(checkpoint, tmp_path):
    path, forced, _source = checkpoint
    out = tmp_path / "cli.pt"
    assert export.main(["--checkpoint", path, "--out", str(out),
                        "--log-level", "ERROR"]) == 0
    assert torch.load(out, weights_only=False)["module_id"] == forced


def test_the_cli_reports_a_bad_module_id_without_a_traceback(checkpoint, tmp_path):
    path, _forced, _source = checkpoint
    assert export.main(["--checkpoint", path, "--module-id", "nope",
                        "--out", str(tmp_path / "x.pt"), "--log-level", "ERROR"]) == 1
