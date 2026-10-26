"""Export recorded Jinni charts to standalone SVG or headless-browser PDF."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

import presentation.svgcharts as svgcharts
from runtime.browser_runtime import run_browser_command
from settings.config import settings
from presentation.export_png import ExportError, find_browser

log = logging.getLogger("jinni.export")
PDF_MAGIC = b"%PDF-"


def export_svg(html_path: Path) -> str:
    """Save a styled standalone SVG next to a genuine Jinni chart page."""
    try:
        svg = svgcharts.export_svg(html_path.read_text(encoding="utf-8"), settings.png_theme)
    except (OSError, ValueError) as e:
        raise ExportError(str(e)) from e
    out = html_path.with_suffix(".svg")
    try:
        out.write_text(svg, encoding="utf-8")
    except OSError as e:
        raise ExportError(f"could not save {out.name} ({type(e).__name__})") from e
    return f"saved {out.name}, {len(svg.encode('utf-8'))} bytes"


def export_pdf(html_path: Path) -> str:
    """Print a genuine Jinni chart page to PDF using the configured headless browser."""
    try:
        page_html = svgcharts.export_page(
            html_path.read_text(encoding="utf-8"), settings.png_theme
        )
    except (OSError, ValueError) as e:
        raise ExportError(str(e)) from e

    browser = find_browser(settings.browser_path)
    if browser is None:
        raise ExportError("no Edge or Chrome was found. Set browser_path in config.py to your browser's .exe file.")

    out = html_path.with_suffix(".pdf")
    with tempfile.TemporaryDirectory(prefix="jinni-pdf-", ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        page, shot = folder / "chart.html", folder / "chart.pdf"
        page.write_text(page_html, encoding="utf-8")
        command = [
            browser,
            settings.png_headless_flag,
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            "--disable-background-networking",
            "--no-pdf-header-footer",
            f"--user-data-dir={folder / 'profile'}",
            f"--window-size={settings.png_width},{settings.png_height}",
            f"--print-to-pdf={shot}",
            page.as_uri(),
        ]
        log.info("pdf export: %s", subprocess.list2cmdline(command))
        try:
            run = run_browser_command(command, settings.png_timeout)
        except subprocess.TimeoutExpired:
            raise ExportError(f"the browser did not finish within {settings.png_timeout:.0f}s") from None
        except OSError as e:
            raise ExportError(f"could not start the browser ({type(e).__name__})") from e

        data = shot.read_bytes() if shot.is_file() else b""
        if not data.startswith(PDF_MAGIC):
            log.warning("pdf export failed, exit code %s, stderr: %r", run.returncode, run.stderr[-500:])
            raise ExportError("the browser did not produce a valid PDF (details are in jinni.log)")

    try:
        out.write_bytes(data)
    except OSError as e:
        raise ExportError(f"could not save {out.name} ({type(e).__name__})") from e
    return f"saved {out.name}, {max(len(data) // 1024, 1)} KB"
