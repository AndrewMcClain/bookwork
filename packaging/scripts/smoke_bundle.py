# Bookwork — a PDF imposition tool for home book binding
# Copyright (C) 2026  Andrew McClain
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check that a PyInstaller bundle actually starts.

The interesting failure for a bundled Qt app is a missing shared library or a
Qt plugin that didn't get collected — the binary exits immediately instead of
opening a window. Importing the package can't catch that, because the bundle
is a separate frozen interpreter with its own copy of everything.

So: launch it, wait, and see whether it is still alive. Staying up is the
pass condition; exiting early is the failure, and its output is what says why.

Written to run identically on all three platforms, since the whole reason it
exists is that Windows and macOS builds have never been verified.

    uv run python packaging/scripts/smoke_bundle.py [--seconds N] [pdf]
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

#: Long enough for Qt to initialise and fail if it is going to; short enough
#: not to pad every CI run.
DEFAULT_SECONDS = 15

_DIST = Path(__file__).resolve().parent.parent / "dist"
#: Where PyInstaller leaves the executable, per platform.
_CANDIDATES = {
    "Darwin": [_DIST / "Bookwork.app/Contents/MacOS/bookwork", _DIST / "bookwork/bookwork"],
    "Windows": [_DIST / "bookwork/bookwork.exe"],
}
_DEFAULT_CANDIDATES = [_DIST / "bookwork/bookwork"]


def find_bundle() -> Path:
    for candidate in _CANDIDATES.get(platform.system(), _DEFAULT_CANDIDATES):
        if candidate.exists():
            return candidate
    searched = "\n  ".join(
        str(c) for c in _CANDIDATES.get(platform.system(), _DEFAULT_CANDIDATES)
    )
    raise SystemExit(f"No built bundle found. Looked for:\n  {searched}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", help="optional PDF to open on launch")
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    args = parser.parse_args()

    binary = find_bundle()
    command = [str(binary)] + ([args.pdf] if args.pdf else [])
    # Offscreen because CI has no display, and because a smoke test should not
    # depend on one either way.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    print(f"launching {binary}")
    process = subprocess.Popen(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            print(f"FAILED — exited after {args.seconds - (deadline - time.monotonic()):.1f}s "
                  f"with code {process.returncode}")
            print(output.strip() or "(no output)")
            return 1
        time.sleep(0.25)

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    print(f"OK — stayed up for {args.seconds}s, so it started cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
