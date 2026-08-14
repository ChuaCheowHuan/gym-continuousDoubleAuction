# 19. Docker — GPU Training Image

The training stack runs in a container so the CUDA runtime, the torch build and the Ray pins move
together as one artefact. This document covers building it, running it (Linux, WSL2, Windows), and
the four failure modes that account for nearly every build or import error.

The image is defined by
[`docker/ml/dockerfile_ray_torch`](../docker/ml/dockerfile_ray_torch). For what the pinned versions
are and why, see [18_configuration.md](18_configuration.md) and `requirements.txt`.

---

## 19.1 Quick start

From the **repository root** (the build context must be the root — `COPY .` copies the project):

```bash
docker build -f docker/ml/dockerfile_ray_torch -t cda-ray-torch .
```

The first build downloads a multi-GB torch wheel and takes a while. Subsequent builds reuse the
apt/torch/ray layers.

Run it, with your working tree mounted so edits take effect immediately:

```bash
docker run --gpus all -it --rm -p 8888:8888 --shm-size=2g \
    -v "$PWD":/workspace/code cda-ray-torch
```

PowerShell needs different quoting — `-v "${PWD}:/workspace/code"`. Then open the
`http://127.0.0.1:8888/?token=...` URL from the container's output and run
[`CDA_NSP.ipynb`](../gym_continuousDoubleAuction/CDA_NSP.ipynb) top to bottom. **Nothing in the
notebook needs editing for this image** — `PLATFORM` and `USE_GPU` are both `auto`, and the
Colab bootstrap cell is a no-op here.

Or run the source exactly as it was at build time, with no mount at all:

```bash
docker run --gpus all -it --rm -p 8888:8888 --shm-size=2g cda-ray-torch
```

Headless training, no notebook:

```bash
docker run --gpus all -it --rm --shm-size=2g -v "$PWD":/workspace/code cda-ray-torch \
    python -m gym_continuousDoubleAuction.train.train
```

No flags: `config/train_config.json` already supplies every value, so the bare command *is* the
configured run. Flags are for deviating from it — `--iters 4` for a smoke test,
`--no-episode-data` to suppress the pickles ([18_configuration.md](18_configuration.md) §2).

### What to check on the first run

The notebook's second cell prints what it resolved. Two lines decide whether the run is doing what
you think:

```
platform         : docker
hardware profile : gpu
```

- **`platform : local`** instead of `docker` — the mount did not land on `/workspace/code`.
  Harmless in itself (the `local` platform relocates nothing), but it means the paths in §19.5 are
  relative to wherever the kernel started.
- **`hardware profile : cpu`** on a machine with a GPU — `--gpus all` did not take, or the toolkit
  is missing. Training still runs, on one core. Go to §19.4.

The profile decides the resource counts, not you: `gpu` gives 2 env runners and a GPU learner,
`cpu` gives one in-process everything. Both are in
[`config/runtime_profiles.json`](../config/runtime_profiles.json), and
[18_configuration.md](18_configuration.md) §8 explains the sizing. If the container has more than
2 CPUs and you want them used, raise `num_env_runners` and `num_cpus` in the `gpu` set together —
runners are Ray actors, and asking for more CPUs than `ray.init()` was given leaves them pending
forever rather than failing.

---

## 19.2 What each flag is for

| Flag | Why it is not optional |
|---|---|
| `--gpus all` | Exposes the GPU. Without it, `runtime.detect_hardware()` selects the `cpu` parameter set and `resolved_gpus_per_learner()` returns 0: training proceeds on one core. Both print a line saying so, but neither fails, so it is easy to miss — check `hardware profile` in the notebook's output. |
| `--shm-size=2g` | Ray's object store lives on `/dev/shm`. Docker's 64MB default makes Ray fall back to `/tmp` and warn about degraded performance. Ray recommends >30% of available RAM. |
| `-p 8888:8888` | Publishes Jupyter. The `CMD` binds `--ip=0.0.0.0`, which is required for the port to be reachable from outside the container. |
| `-it` | Keeps the Jupyter token visible and `Ctrl-C` working. |
| `--rm` | Deletes the container on exit. Anything you want to keep must be on the mount — see §19.5. |

---

## 19.3 Three design decisions worth knowing

### The project is installed into the image, editable

The last two layers `COPY` the source to `/workspace/code` and `pip install --no-deps -e` it. This
matters because of where the notebook lives:
[`CDA_NSP.ipynb`](../gym_continuousDoubleAuction/CDA_NSP.ipynb) sits *inside* the package directory,
so the path Jupyter puts on `sys.path` is the package directory itself, never the repository root.
`import gym_continuousDoubleAuction` cannot resolve from there by accident — the package has to be
genuinely installed.

An editable install records a **path**, not a copy. That single fact gives both run modes:

- **No mount** — imports resolve against the baked-in copy. The image is self-contained and
  portable to a training box or CI.
- **Mount at `/workspace/code`** — the bind mount shadows the baked copy, and the recorded path now
  points at your live working tree. Edits take effect on the next kernel restart.

**Mount the repository root, not its parent.** Mounting the parent puts the repo one level down at
`/workspace/code/<repo-name>`, so the recorded path no longer points at a package tree and imports
break in a way that reads like a missing install.

`--no-deps` is deliberate: every entry in `setup.py`'s `install_requires` is already installed by the
layer above, at versions chosen to match this CUDA build. Letting pip re-resolve risks it quietly
swapping one. The tradeoff — **a dependency added to `setup.py` will not be installed by that line**.
Add it to the explicit `pip install` block in the Dockerfile too.

### Everything installs into a venv at `/opt/venv`

Ubuntu 24.04 marks the system Python externally-managed (PEP 668). `PIP_BREAK_SYSTEM_PACKAGES=1` is
not sufficient on its own: apt's pip ships without a `RECORD` file, so `pip install --upgrade pip`
fails outright with `Cannot uninstall pip 24.0, RECORD file not found`.

A venv sidesteps it and keeps the pinned scientific stack from colliding with distro packages.
`PATH` puts `/opt/venv/bin` first, so plain `pip`, `python` and `jupyter` resolve there — in the
`CMD`, in `docker exec` shells, and as the notebook kernel's `sys.executable`.

### The CUDA minor and the wheel index are one decision

The base image is `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04` and torch comes from the `cu128`
index. **Changing one without the other produces an image that builds and then fails at runtime.**

The host driver does not need to match. Driver-to-runtime compatibility is forward-looking, so a
driver advertising a *newer* CUDA than 12.8 runs the cu128 wheels fine. `nvidia-smi` reporting
"CUDA Version: 13.1" is the driver's maximum supported version, not what is installed.

---

## 19.4 GPU prerequisites

Verify passthrough before building anything — it isolates driver problems from build problems:

```bash
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

Your GPU in the output means `--gpus all` works and the rest will too.

**Linux** — install `nvidia-container-toolkit` and restart the Docker daemon.

**WSL2** — either Docker Desktop with WSL integration enabled for the distro, or Docker Engine
inside the distro plus `nvidia-container-toolkit`. **Do not install an NVIDIA driver inside WSL**;
the Windows host driver provides `/dev/dxg`. A process named `/Xwayland` holding a few hundred MB in
`nvidia-smi` is WSLg's compositor and is expected.

**Working tree location under WSL2 matters.** A repo on the Windows drive is reachable at
`/mnt/c/...`, but that path goes through the 9p translation layer and is slow — both for the build
context copy and, more importantly, for the per-episode pickles described below. For regular
training, clone into the Linux filesystem (`~/code/...`) instead.

---

## 19.5 Artefacts and the ephemeral container

With `--rm`, everything written inside the container is destroyed on exit. Training writes several
things worth keeping, all of them **relative to the working directory** — `/workspace/code`:

| Written | By |
|---|---|
| `episode_data/` — one pickle per episode | `SelfPlayCallback`, when `TrainConfig.episode_data_dir` is set |
| `results/chkpt/iter_*/` | `save_checkpoint()` in `train()`, under `TrainConfig.checkpoint_dir` — `log_base_dir` + `chkpt`. The newest `chkpt_keep` are retained |

`CDA_NSP.ipynb` gets there too: Jupyter starts a kernel in the *notebook's* directory, which is
`/workspace/code/gym_continuousDoubleAuction`, so the notebook calls `runtime.chdir_to_repo()` to
move to the `repo_path` its platform declares. Without that, notebook runs and
`python -m ...train` runs would write to two different `results/` directories one level apart.

Mounting the repo root at `/workspace/code` means these land in your real working tree and survive.
Both are already in [`.gitignore`](../.gitignore) and [`.dockerignore`](../.dockerignore), so they
are neither committed nor copied back into the next image build.

Checkpoints are the ones that matter: without a mount, `--rm` discards them and
`TrainConfig.is_restore` has nothing to resume from.

At `max_step=4096`, `episode_data` is one file per episode and a lot of I/O. Set
`episode_data_dir=None` to turn it off. This is the write path that makes a `/mnt/c` mount hurt under
WSL2.

---

## 19.6 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'gym_continuousDoubleAuction'` | The image predates the baked-in editable install, or the mount landed somewhere other than `/workspace/code`. | Rebuild. Check `ls /workspace/code/setup.py` inside the container. |
| `does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found` | Mounted the repo's parent instead of the repo root. | Run `docker run` from the repository root. |
| `requires a different Python: 3.10.12 not in '>=3.12'` | Building on an Ubuntu 22.04 base, which ships Python 3.10. `setup.py` requires >=3.12. | Use the 24.04 base in the current Dockerfile. Do not force with `--ignore-requires-python`: `pandas>=3.0` and `numpy>=2.5` have no 3.10 wheels. |
| `Cannot uninstall pip 24.0, RECORD file not found` | PEP 668 system Python. | Already handled by the venv — rebuild with the current Dockerfile. |
| Ray warns about `/dev/shm` and degraded performance | Docker's 64MB shm default. | `--shm-size=2g`. |
| `torch.cuda.is_available()` is `False` | `--gpus all` omitted, or the toolkit is not installed. | Run the §19.4 check. |
| The notebook prints `hardware profile : cpu` on a GPU box | Same cause as the row above — the profile follows `torch.cuda.is_available()`. | Run the §19.4 check. `USE_GPU=True` will *not* override it; it falls back and says so rather than placing a learner on a device that is not there. |
| Training hangs after `ray.init()` with no error | An edited profile asks for more CPUs than `ray.init()` was given (`num_env_runners × num_cpus_per_env_runner > num_cpus`). Env runners are actors: they stay **pending**, which looks like a hang. | Raise `ray_init.num_cpus` in the same profile, or lower the runner count. `test_runtime_profiles.py` pins this for the shipped sets. |
| Build is slow on every source edit | Expected. `COPY .` is the last layer by design; only it and the editable install re-run. | Nothing to fix — if the *torch* layer rebuilds, something above it changed. |

---

## 19.7 Related

- [20_colab.md](20_colab.md) — the other supported target, for when there is no local GPU
- [02_architecture.md](02_architecture.md) — where the container sits in the overall stack
- [09_distributed_training.md](09_distributed_training.md) — Ray env runners and learner placement,
  which is what `--shm-size` and `--gpus` actually feed
- [18_configuration.md](18_configuration.md) — `TrainConfig`, including `episode_data_dir` and
  `num_gpus_per_learner`; §8 covers `runtime_profiles.json`, which is what makes `CDA_NSP.ipynb`
  run unchanged in this image and on Colab
