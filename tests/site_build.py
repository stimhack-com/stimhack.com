"""Build the site once per test run, for tests that check rendered pages."""
import atexit
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@cache
def build():
    """Build the site with Hugo into a temporary directory and return its path."""
    out = Path(tempfile.mkdtemp(prefix="stimhack-build-"))
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    subprocess.run(
        ["nix", "run", "nixpkgs#hugo", "--", "--source", str(ROOT), "--destination", str(out), "--quiet"],
        check=True,
    )
    return out
