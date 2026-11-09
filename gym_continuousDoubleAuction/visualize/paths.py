"""Where `visualize/` writes, from config rather than from the working directory.

Issue #359: every chart script had a literal `visualize/chart/...` output path,
so running `python -m ...visualize.run_all` from the repository root created a
second `./visualize/chart/` there instead of updating the tracked charts under
the package. The input side already reads `visualize_paths` from
`config/tunable_constants.json`; this is the same rule for the output side.

A configured path is resolved against the package directory, not the current
working directory, unless it is absolute. `out_dir` - the `--out-dir` flag - is
resolved the same way and overrides the configured directory.
"""

from pathlib import Path

from gym_continuousDoubleAuction.config_loader import constant

#: `gym_continuousDoubleAuction/`, the directory the configured
#: `visualize/chart` and `visualize/json` paths are relative to. Not
#: `visualize/` itself: the configured values name the `visualize` component.
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def directory(key: str, out_dir=None) -> Path:
    """The output directory for `key` (`chart_dir` or `dump_dir`), absolute."""
    base = Path(out_dir) if out_dir is not None else Path(constant("visualize_paths", key))
    if not base.is_absolute():
        base = PACKAGE_ROOT / base
    return base


def output_path(key: str, filename: str, out_dir=None) -> Path:
    """One output file under `directory(key, out_dir)`."""
    return directory(key, out_dir) / filename
