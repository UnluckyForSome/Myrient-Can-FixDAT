"""
retool Integration Layer
========================
Wraps retool (https://github.com/unexpectedpanda/retool) as a subprocess
for post-processing synthetic DATs generated from the Minerva index.

Architecture:
- Subprocess boundary (stable CLI interface; retool is unmaintained).
- Preset library for common use cases.
- Temp file management: synthetic DAT → retool → filtered DAT → parse.
- Swappable to programmatic import (v2) via the same RetoolPipeline interface.
"""
from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404  # noqa: S404
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

# ── Presets ─────────────────────────────────────────────────────────────────────

RETOOL_PRESETS: dict[str, "RetoolPreset"] = {}

@dataclass
class RetoolPreset:
    """A reusable retool configuration preset."""
    name: str
    label: str
    description: str
    exclude_flags: str = ""
    extra_args: list[str] = field(default_factory=list)
    config_hint: str = ""


def _register_presets():
    if RETOOL_PRESETS:
        return
    for p in [
        RetoolPreset(
            name="translations-en-latest",
            label="Translations – English Latest",
            description="Latest English translations, no betas/protos/demos",
            exclude_flags="Pdr",
            extra_args=["--compilations", "i", "-l"],
            config_hint="Set language order to English in retool config.",
        ),
        RetoolPreset(
            name="aftermarket-1g1r",
            label="Aftermarket 1G1R",
            description="Aftermarket + homebrew titles, one game one ROM",
            exclude_flags="PdbBR",
            extra_args=["--compilations", "i"],
            config_hint="Default region order.",
        ),
        RetoolPreset(
            name="prototypes",
            label="Prototypes & Preproduction",
            description="Keep all alphas, betas, prototypes, demos",
            exclude_flags="",
            extra_args=["--compilations", "i"],
            config_hint="Disable 1G1R if you want all variants.",
        ),
        RetoolPreset(
            name="full-no-intro",
            label="Everything (No 1G1R)",
            description="All titles, no dedup, exclude nothing",
            exclude_flags="",
            extra_args=["-d"],
            config_hint="Disables 1G1R — every matching entry passes through.",
        ),
        RetoolPreset(
            name="full-no-aftermarket",
            label="No Aftermarket",
            description="Exclude aftermarket, keep everything else",
            exclude_flags="f",
            extra_args=["--compilations", "i"],
            config_hint="",
        ),
    ]:
        RETOOL_PRESETS[p.name] = p


def get_preset(name: str) -> RetoolPreset | None:
    """Look up a preset by name."""
    _register_presets()
    return RETOOL_PRESETS.get(name)


def list_presets() -> list[RetoolPreset]:
    """Return all available presets."""
    _register_presets()
    return list(RETOOL_PRESETS.values())


def retool_available() -> bool:
    """Check if retool is installed and on PATH."""
    return shutil.which("retool") is not None


class RetoolError(Exception):
    """Raised when retool subprocess fails."""


class RetoolPipeline:
    """Wraps retool as a subprocess for filtering synthetic DATs.

    Usage:
        pipe = RetoolPipeline()
        if not pipe.available():
            # tell user to pip install retool
            return
        result_path = pipe.run(input_dat="/tmp/synthetic.dat",
                               output_dir="/tmp/filtered",
                               preset=get_preset("translations-en-latest"))
    """

    def __init__(self, retool_path: str | None = None):
        self._retool_path = retool_path or "retool"

    def available(self) -> bool:
        """Check whether retool is reachable."""
        return shutil.which(self._retool_path) is not None

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def run(
        self,
        input_dat: str | Path,
        output_dir: str | Path | None = None,
        preset: RetoolPreset | None = None,
        exclude_flags: str = "",
        extra_args: Sequence[str] = (),
    ) -> Path:
        """Run retool on a synthetic DAT file.

        Args:
            input_dat: Path to the synthetic .dat file.
            output_dir: Where retool writes output. Defaults to a temp dir.
            preset: Optional preset config.
            exclude_flags: E.g. "Pdr" mapped to ``--exclude Pdr``.
            extra_args: Additional CLI args, e.g. ``["-d"]`` to disable 1G1R.

        Returns:
            Path to the filtered .dat file.

        Raises:
            RetoolError: If retool is unavailable or the subprocess fails.
        """
        if not self.available():
            raise RetoolError(
                "retool is not installed. Run: pip install retool"
            )

        input_path = Path(input_dat).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Input DAT not found: {input_path}")

        out_dir = self._resolve_output_dir(output_dir)
        cmd = self._build_argv(input_path, preset, exclude_flags, extra_args, out_dir)
        self._execute(cmd)
        return self._find_output_file(out_dir)

    def _resolve_output_dir(
        self, output_dir: str | Path | None,
    ) -> Path:
        if output_dir is None:
            return Path(tempfile.mkdtemp(prefix="retool_"))
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def _build_argv(
        self,
        input_path: Path,
        preset: RetoolPreset | None,
        exclude_flags: str,
        extra_args: Sequence[str],
        output_dir: Path,
    ) -> list[str]:
        cmd = [self._retool_path, str(input_path)]
        if preset:
            if preset.exclude_flags:
                cmd.extend(["--exclude", preset.exclude_flags])
            cmd.extend(preset.extra_args)
        if exclude_flags:
            cmd.extend(["--exclude", exclude_flags])
        cmd.extend(extra_args)
        cmd.extend(["--output", str(output_dir)])
        return cmd

    @staticmethod
    def _execute(cmd: list[str]) -> None:
        log.debug("retool command: %s", " ".join(cmd))
        try:
            result = subprocess.run(  # nosec B603  # noqa: S603
                cmd, capture_output=True, text=True, timeout=300, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RetoolError("retool timed out after 300s") from exc
        except FileNotFoundError as exc:
            raise RetoolError(
                "retool binary not found. Install with: pip install retool"
            ) from exc
        if result.returncode != 0:
            stderr = result.stderr.strip()
            log.error("retool failed (exit %d): %s", result.returncode, stderr)
            raise RetoolError(
                f"retool exited with code {result.returncode}:\n{stderr}"
            )

    @staticmethod
    def _find_output_file(output_dir: Path) -> Path:
        out_files = sorted(output_dir.rglob("*.dat"), key=lambda p: p.stat().st_size, reverse=True)
        if not out_files:
            log.warning("retool produced no .dat output (empty filter result?)")
            return output_dir / "empty.dat"
        log.info("retool output: %s", out_files[0].name)
        return out_files[0]

    def __repr__(self) -> str:
        return f"RetoolPipeline(path={self._retool_path!r}, available={self.available()})"
