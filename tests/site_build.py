"""Build the site once per test run, for tests that check rendered pages."""
import atexit
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
# hugo.toml with the main menu of the fixture sites in FIXTURES.
FIXTURE_CONFIG = f"{ROOT / 'hugo.toml'},{FIXTURES / 'menu.toml'}"


@cache
def build(content=None, environment=None):
    """Build the site with Hugo into a temporary directory and return its path.

    content is a directory to use in place of content/, for tests with their own posts.
    A directory in FIXTURES gets the main menu of FIXTURE_CONFIG.
    environment is a Hugo environment such as "staging", which adds config/<environment>/.
    """
    out = Path(tempfile.mkdtemp(prefix="stimhack-build-"))
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    args = ["--source", str(ROOT), "--destination", str(out), "--quiet"]
    if content:
        args += ["--contentDir", str(content)]
        if Path(content).is_relative_to(FIXTURES):
            args += ["--config", FIXTURE_CONFIG]
    if environment:
        args += ["--environment", environment]
    subprocess.run([*hugo(), *args], check=True)
    return out


def hugo():
    """Return the command that runs Hugo."""
    # CI (.github/workflows/site.yml) installs Hugo on PATH and has no nix;
    # local machines run it through nix.
    return ["hugo"] if shutil.which("hugo") else ["nix", "run", "nixpkgs#hugo", "--"]
