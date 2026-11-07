"""Build the site once per test run, for tests that check rendered pages."""
import atexit
import csv
import os
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
def build(content=None):
    """Build the site with Hugo into a temporary directory and return its path.

    content is a directory to use in place of content/, for tests with their own posts.
    A directory in FIXTURES gets the main menu of FIXTURE_CONFIG.
    """
    out = Path(tempfile.mkdtemp(prefix="stimhack-build-"))
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    args = ["--source", str(ROOT), "--destination", str(out), "--quiet", *config_args(content)]
    if content:
        args += ["--contentDir", str(content)]
    subprocess.run([*hugo(), *args], check=True)
    return out


@cache
def published_pages(content):
    """Return a row of `hugo list published` for each page that Hugo publishes from the directory content.

    Each row is a dict with the columns path, slug, title, date, expiryDate,
    publishDate, draft, permalink, kind and section, and path is the absolute
    path of the content file. build() makes the site from the same content
    and config. `hugo list` has no --contentDir flag, so the directory goes in
    HUGO_CONTENTDIR: Hugo sets a config key from each environment variable
    HUGO_<key> (config/allconfig/load.go in the Hugo source). It gets no
    --quiet, which sends the list to io.Discard (commands/commandeer.go).
    """
    run = subprocess.run(
        [*hugo(), "list", "published", "--source", str(ROOT), *config_args(content)],
        env=os.environ | {"HUGO_CONTENTDIR": str(content)},
        stdout=subprocess.PIPE, text=True, check=True,
    )
    rows = list(csv.DictReader(run.stdout.splitlines()))
    for row in rows:
        row["path"] = (ROOT / row["path"]).resolve()
    return rows


def config_args(content):
    """Return the Hugo arguments that give a directory content in FIXTURES the config FIXTURE_CONFIG."""
    return ["--config", FIXTURE_CONFIG] if content and Path(content).is_relative_to(FIXTURES) else []


def hugo():
    """Return the command that runs Hugo."""
    # CI (.github/workflows/site.yml) installs Hugo on PATH and has no nix;
    # local machines run it through nix.
    return ["hugo"] if shutil.which("hugo") else ["nix", "run", "nixpkgs#hugo", "--"]
