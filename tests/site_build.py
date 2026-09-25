"""Build the site once per test run, for tests that check rendered pages."""
import atexit
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@cache
def build(content=None):
    """Build the site with Hugo into a temporary directory and return its path.

    content is a directory to use in place of content/, for tests with their own posts.
    """
    out = Path(tempfile.mkdtemp(prefix="stimhack-build-"))
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    # CI (.github/workflows/site.yml) installs Hugo on PATH and has no nix;
    # local machines run it through nix.
    hugo = ["hugo"] if shutil.which("hugo") else ["nix", "run", "nixpkgs#hugo", "--"]
    args = ["--source", str(ROOT), "--destination", str(out), "--quiet"]
    if content:
        args += ["--contentDir", str(content)]
    subprocess.run([*hugo, *args], check=True)
    return out
