"""Ground truth for the docs sync, computed from the code. Read-only over the repo."""
import json
import logging
import os
import re
import subprocess
import sys

logging.disable(logging.CRITICAL)
ROOT = sys.argv[1]
OUT = sys.argv[2]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
facts = {}


def collect(path, ignore=None):
    cmd = [sys.executable, "-m", "pytest", path, "--collect-only", "-q", "-p", "no:cacheprovider"]
    if ignore:
        cmd += [f"--ignore={ignore}"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    per_file = {}
    for line in out.splitlines():
        m = re.match(r"(gym_continuousDoubleAuction/test/\S+?\.py)::", line)
        if m:
            per_file[m.group(1)] = per_file.get(m.group(1), 0) + 1
    total = int(re.search(r"(\d+) tests? collected", out).group(1))
    return total, per_file


unit, unit_files = collect("gym_continuousDoubleAuction/test", "gym_continuousDoubleAuction/test/integration")
integ, integ_files = collect("gym_continuousDoubleAuction/test/integration")
facts["tests"] = {"unit": unit, "integration": integ, "total": unit + integ,
                  "per_file": {**unit_files, **integ_files},
                  "unit_files": len(unit_files), "integration_files": len(integ_files)}

from gym_continuousDoubleAuction.train.train import TrainConfig  # noqa: E402
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv  # noqa: E402
from gym_continuousDoubleAuction.envs.exchg import state_helper as sh  # noqa: E402
from gym_continuousDoubleAuction.config_loader import load  # noqa: E402

cfg = TrainConfig()


def space(env):
    a = env.agents[0]
    return env.get_observation_space(a), env.get_action_space(a)


obs_t, act_t = space(continuousDoubleAuctionEnv(cfg.env_config))
bare = continuousDoubleAuctionEnv({})
obs_b, _ = space(bare)
levels = continuousDoubleAuctionEnv({**cfg.env_config, "book_mode": "levels"})
obs_l, _ = space(levels)
facts["obs"] = {
    "train_width": int(obs_t.shape[0]), "bare_width": int(obs_b.shape[0]),
    "levels_width": int(obs_l.shape[0]),
    "n_hist": cfg.n_hist, "grid_snapshot": int(continuousDoubleAuctionEnv(cfg.env_config).snapshot_dim),
    "levels_snapshot": int(levels.snapshot_dim),
    "private_dim": len(sh.private_fields(sh.K_ROWS)), "private_fields": list(sh.private_fields(sh.K_ROWS)),
    "base_private": len(sh.BASE_PRIVATE_FIELDS), "mask_fields": len(sh.MASK_FIELDS),
    "extra_dim": load("tunable_constants.json")["observation_layout"]["extra_dim"],
}
facts["action"] = {k: str(v) for k, v in act_t.spaces.items()}
facts["action"]["_heads"] = len(act_t.spaces)

from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS  # noqa: E402
facts["reward_terms"] = list(REWARD_TERMS)

from gym_continuousDoubleAuction.train.model.encoders import selectable_encoder_types  # noqa: E402
facts["encoders"] = list(selectable_encoder_types())

facts["config"] = {f: load(f) for f in ("train_config.json", "env_defaults.json", "tunable_constants.json",
                                         "cli_defaults.json", "runtime_profiles.json")}
facts["train_defaults"] = {"num_agents": cfg.num_agents, "num_trained_agents": cfg.num_trained_agents,
                           "max_step": cfg.max_step, "init_cash": cfg.init_cash, "num_iters": cfg.num_iters}

flags = {}
for mod in ("CDA_rand", "train.train", "train.probe", "train.pretrain", "train.compare",
            "train.evaluate", "train.export", "visualize.run_all"):
    out = subprocess.run([sys.executable, "-m", f"gym_continuousDoubleAuction.{mod}", "--help"],
                         capture_output=True, text=True).stdout
    flags[mod] = sorted(set(re.findall(r"(--[a-z][a-z0-9-]*)", out)))
facts["flags"] = flags

tree = []
for dirpath, dirnames, filenames in os.walk("gym_continuousDoubleAuction"):
    dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "test")]
    tree += [os.path.join(dirpath, f) for f in filenames if f.endswith((".py", ".ipynb"))]
facts["files"] = sorted(tree)

json.dump(facts, open(OUT, "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in facts.items() if k not in ("config", "files", "flags")}, default=str)[:3000])
