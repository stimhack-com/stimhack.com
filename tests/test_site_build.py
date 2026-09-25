"""Tests for the Hugo command that the site build helper runs."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import site_build


def fake_program(bin_dir, name, argv_file):
    """Write an executable that records its arguments in argv_file."""
    path = Path(bin_dir) / name
    path.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{argv_file}"\n')
    path.chmod(0o755)


class HugoCommand(unittest.TestCase):
    def run_build_with_only(self, name):
        """Run an uncached build with a PATH that holds only a fake `name`, and return its arguments."""
        with tempfile.TemporaryDirectory() as bin_dir:
            argv_file = Path(bin_dir) / "argv"
            fake_program(bin_dir, name, argv_file)
            with mock.patch.dict(os.environ, {"PATH": bin_dir}):
                out = site_build.build.__wrapped__()
            return argv_file.read_text().splitlines(), out

    def test_uses_hugo_from_path_when_there_is_no_nix(self):
        # CI installs Hugo from the release package and has no nix.
        argv, out = self.run_build_with_only("hugo")
        self.assertEqual(argv, ["--source", str(site_build.ROOT), "--destination", str(out), "--quiet"])

    def test_falls_back_to_nix_when_hugo_is_not_on_path(self):
        argv, out = self.run_build_with_only("nix")
        self.assertEqual(
            argv,
            ["run", "nixpkgs#hugo", "--", "--source", str(site_build.ROOT), "--destination", str(out), "--quiet"],
        )


if __name__ == "__main__":
    unittest.main()
