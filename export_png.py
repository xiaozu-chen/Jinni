from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import svgcharts
from browser_runtime import run_browser_command
from config import settings

log = logging.getLogger("jinni.png")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_SIDE = 20_000
MIN_WIDTH, MAX_WIDTH = 320, 7680
MIN_HEIGHT, MAX_HEIGHT = 240, 4320

CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)


class ExportError(Exception):
    """PNG export failed. The message is written for the user."""


def parse_export_options(text: str) -> tuple[str, str | None, int | None, int | None]:
    """Parse `/png [chart] [theme] [WIDTHxHEIGHT]` options."""
    theme = None
    size = None
    name = None
    for part in text.split():
        value = part.lower()
        if value in ("light", "dark"):
            if theme is not None:
                raise ValueError("choose one theme: light or dark")
            theme = value
        elif "x" in value and any(character.isdigit() for character in value):
            if size is not None:
                raise ValueError("give one size as WIDTHxHEIGHT")
            pieces = value.split("x")
            if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
                raise ValueError("size must look like 1280x720")
            width, height = map(int, pieces)
            if not (MIN_WIDTH <= width <= MAX_WIDTH and MIN_HEIGHT <= height <= MAX_HEIGHT):
                raise ValueError(
                    f"size must be between {MIN_WIDTH}x{MIN_HEIGHT} and {MAX_WIDTH}x{MAX_HEIGHT}"
                )
            size = (width, height)
        else:
            if name is not None:
                raise ValueError("use /png [chart] [light|dark] [WIDTHxHEIGHT]")
            name = part
    width, height = size if size is not None else (None, None)
    return name or "", theme, width, height


def png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) read from a PNG header, or None if this is not a sane PNG."""
    if len(data) < 24 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        return None
    return width, height


def find_browser(configured: str = "") -> str | None:
    if configured:
        return configured if Path(configured).is_file() else None
    for pattern in CANDIDATES:
        path = os.path.expandvars(pattern)
        if "%" not in path and Path(path).is_file():
            return path
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_command(browser: str, page: Path, shot: Path, profile: Path,
                  width: int, height: int, scale: float) -> list[str]:
    return [
        browser,
        settings.png_headless_flag,
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--disable-extensions",
        "--disable-background-networking",
        f"--user-data-dir={profile}",
        f"--force-device-scale-factor={scale:g}",
        f"--window-size={width},{height}",
        f"--screenshot={shot}",
        page.as_uri(),
    ]


def render_png(page_html: str, out_path: Path, width: int | None = None,
               height: int | None = None) -> tuple[int, int, int]:
    """Screenshot a page to out_path. Returns (width, height, bytes)."""
    browser = find_browser(settings.browser_path)
    if browser is None:
        raise ExportError("no Edge or Chrome was found. Set browser_path in config.py to your browser's .exe file.")

    with tempfile.TemporaryDirectory(prefix="jinni-png-", ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        page, shot = folder / "chart.html", folder / "shot.png"
        page.write_text(page_html, encoding="utf-8")
        command = build_command(browser, page, shot, folder / "profile",
                                settings.png_width if width is None else width,
                                settings.png_height if height is None else height,
                                settings.png_scale)
        log.info("png export: %s", subprocess.list2cmdline(command))
        try:
            run = run_browser_command(command, settings.png_timeout)
        except subprocess.TimeoutExpired:
            raise ExportError(f"the browser did not finish within {settings.png_timeout:.0f}s") from None
        except OSError as e:
            raise ExportError(f"could not start the browser ({type(e).__name__})") from e

        data = shot.read_bytes() if shot.is_file() else b""
        size = png_size(data)
        if size is None:
            log.warning("png export failed, exit code %s, stderr: %r", run.returncode, run.stderr[-500:])
            raise ExportError("the browser did not produce a valid PNG (details are in jinni.log)")

    out_path.write_bytes(data)
    return size[0], size[1], len(data)


def export_chart(html_path: Path, theme: str | None = None, width: int | None = None,
                 height: int | None = None) -> str:
    """Rebuild a chart page for export, render it, save the PNG next to it. Returns a summary."""
    try:
        page = svgcharts.export_page(html_path.read_text(encoding="utf-8"), theme or settings.png_theme)
    except (OSError, ValueError) as e:
        raise ExportError(str(e)) from e
    out = html_path.with_suffix(".png")
    out_width = settings.png_width if width is None else width
    out_height = settings.png_height if height is None else height
    if not (MIN_WIDTH <= out_width <= MAX_WIDTH and MIN_HEIGHT <= out_height <= MAX_HEIGHT):
        raise ExportError(
            f"PNG size must be between {MIN_WIDTH}x{MIN_HEIGHT} and {MAX_WIDTH}x{MAX_HEIGHT}"
        )
    actual_width, actual_height, size = render_png(page, out, out_width, out_height)
    return f"saved {out.name}, {actual_width}x{actual_height}, {max(size // 1024, 1)} KB"
