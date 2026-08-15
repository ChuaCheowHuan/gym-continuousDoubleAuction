#!/bin/bash
# Prepare a Claude Code on the web session to actually run this project.
#
# Two things make a bare container unable to run the test suite:
#
#   1. The default python3 in the image is 3.11, and requirements.txt pins
#      scipy>=1.18, which ships no 3.11 wheels. `pip install -r requirements.txt`
#      fails outright. setup.py already declares python_requires=">=3.12"; this
#      builds the venv with 3.12 to match it and CI.
#
#   2. CI installs torch from https://download.pytorch.org/whl/cpu. That host is
#      not reachable through the web sandbox's egress proxy, so this hook lets
#      torch resolve from PyPI instead. The only difference is the bundled
#      nvidia-* runtime packages, which nothing here uses on CPU.
#
# Idempotent: the venv is reused across sessions, and pip re-runs are no-ops
# once the container state is cached.
set -euo pipefail

# Local checkouts already have a working environment; this is remote-only.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VENV="$REPO/.venv"   # already covered by .gitignore

cd "$REPO"

# 3.12 specifically: 3.13 is not what CI tests and Ray 2.56.1 does not ship
# wheels for every 3.13 dependency combination this project pins.
PY=""
for candidate in python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "session-start: no Python 3.12 interpreter found; this project requires it" >&2
  echo "session-start: found python3 = $(python3 --version 2>&1 || echo none)" >&2
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "session-start: creating $VENV with $($PY --version)"
  "$PY" -m venv "$VENV"
fi

echo "session-start: installing dependencies"
# setuptools/wheel explicitly rather than relying on `pip install -e .` to pull
# a build backend in: setup.py is a legacy (non-PEP-517-declaring) build, so the
# backend needs to be present in the venv rather than assumed.
#
# Unrelated cosmetic note: `python3.12 -m venv` above prints a _distutils_hack
# traceback on first run. That comes from the *system* interpreter's
# /usr/lib/python3/dist-packages/distutils-precedence.pth while it builds the
# venv - not from the venv, which runs clean. It is harmless and first-run only.
"$VENV/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install --quiet -r requirements.txt
"$VENV/bin/python" -m pip install --quiet -e ".[dev]"

# Put the venv ahead of the system interpreter for the rest of the session, so
# `python`, `pip` and `pytest` are the project's without needing the full path.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export VIRTUAL_ENV=$VENV"
    echo "export PATH=$VENV/bin:\$PATH"
  } >> "$CLAUDE_ENV_FILE"
fi

echo "session-start: ready - $("$VENV/bin/python" --version)"
