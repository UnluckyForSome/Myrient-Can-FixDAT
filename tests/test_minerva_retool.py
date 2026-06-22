"""
Tests for minerva_retool.py
============================
Run with: python -m pytest tests/test_minerva_retool.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from minerva_retool import (
    RETOOL_PRESETS,
    RetoolError,
    RetoolPipeline,
    RetoolPreset,
    get_preset,
    list_presets,
)


class TestRetoolPresets(unittest.TestCase):
    """Test preset system."""

    def test_list_presets_returns_all(self):
        presets = list_presets()
        self.assertEqual(len(presets), len(RETOOL_PRESETS))

    def test_get_preset_returns_correct_keys(self):
        p = get_preset("translations-en-latest")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "translations-en-latest")
        self.assertIn("Translation", p.label)

    def test_get_preset_unknown_returns_none(self):
        self.assertIsNone(get_preset("nonexistent"))

    def test_preset_has_exclude_flags(self):
        p = get_preset("aftermarket-1g1r")
        self.assertTrue(len(p.exclude_flags) > 0)

    def test_preset_full_no_intro_disables_1g1r(self):
        p = get_preset("full-no-intro")
        self.assertIn("-d", p.extra_args)


class TestRetoolPipeline(unittest.TestCase):
    """Test retool pipeline (mocked — retool may not be installed)."""

    def setUp(self):
        self.pipe = RetoolPipeline()

    def test_available_false_when_not_installed(self):
        """By default retool probably isn't installed in test env."""
        with patch("shutil.which", return_value=None):
            self.assertFalse(self.pipe.available())

    def test_available_true_when_installed(self):
        with patch("shutil.which", return_value="/usr/bin/retool"):
            self.assertTrue(self.pipe.available())

    def test_run_raises_when_not_available(self):
        with patch.object(self.pipe, "available", return_value=False):
            with self.assertRaises(RetoolError) as ctx:
                self.pipe.run("/nonexistent.dat")
            self.assertIn("not installed", str(ctx.exception))

    def test_run_raises_on_nonexistent_input(self):
        with patch.object(self.pipe, "available", return_value=True):
            with self.assertRaises(FileNotFoundError):
                self.pipe.run("/nonexistent/path.dat")

    def test_run_subprocess_failure(self):
        with (
            patch.object(self.pipe, "available", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "Config error: bad region"

            import tempfile
            f = tempfile.NamedTemporaryFile(suffix=".dat", delete=False)
            f.write(b"<datafile/>")
            f.close()
            try:
                with self.assertRaises(RetoolError) as ctx:
                    self.pipe.run(Path(f.name))
                self.assertIn("code 1", str(ctx.exception))
                self.assertIn("Config error", str(ctx.exception))
            finally:
                Path(f.name).unlink()

    def test_run_subprocess_timeout(self):
        import subprocess
        with (
            patch.object(self.pipe, "available", return_value=True),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="retool", timeout=300)),
        ):
            import tempfile
            f = tempfile.NamedTemporaryFile(suffix=".dat", delete=False)
            f.write(b"<datafile/>")
            f.close()
            try:
                with self.assertRaises(RetoolError):
                    self.pipe.run(Path(f.name))
            finally:
                Path(f.name).unlink()

    def test_repr(self):
        r = repr(self.pipe)
        self.assertIn("RetoolPipeline", r)


class TestRetoolPresetDataclass(unittest.TestCase):
    """Test RetoolPreset dataclass."""

    def test_creates_preset_with_minimal_args(self):
        p = RetoolPreset(name="test", label="Test", description="A test")
        self.assertEqual(p.name, "test")
        self.assertEqual(p.exclude_flags, "")
        self.assertEqual(p.extra_args, [])

    def test_creates_preset_with_all_args(self):
        p = RetoolPreset(
            name="full",
            label="Full Test",
            description="Full preset test",
            exclude_flags="Pdr",
            extra_args=["-l"],
            config_hint="Set English",
        )
        self.assertEqual(p.exclude_flags, "Pdr")
        self.assertEqual(p.extra_args, ["-l"])
        self.assertEqual(p.config_hint, "Set English")


if __name__ == "__main__":
    unittest.main(verbosity=2)
