import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import export_formats
import svgcharts
from config import settings
from export_formats import export_pdf, export_svg
from export_png import ExportError
from tools.charts import make_chart


class FakeBrowser:
    def __init__(self):
        self.output = b"%PDF-1.7\nchart\n%%EOF"
        self.command = []
        self.page_html = ""
        self.error = None

    def __call__(self, command, **kwargs):
        self.command = command
        if self.error:
            raise self.error
        profile = next(part for part in command if part.startswith("--user-data-dir="))
        self.page_html = (Path(profile.split("=", 1)[1]).parent / "chart.html").read_text(
            encoding="utf-8"
        )
        target = next(part for part in command if part.startswith("--print-to-pdf="))
        Path(target.split("=", 1)[1]).write_bytes(self.output)
        return subprocess.CompletedProcess(command, 0, b"", b"")


@pytest.fixture
def chart(workspace):
    (workspace / "sales.csv").write_text("month,revenue\nJan,10\nFeb,15\n", encoding="utf-8")
    assert make_chart("sales.csv", "month", "revenue").startswith("Saved")
    return workspace / "charts" / "sales-revenue-bar.html"


@pytest.fixture
def browser(monkeypatch):
    fake = FakeBrowser()
    monkeypatch.setattr(export_formats, "find_browser", lambda configured="": "fake-browser")
    monkeypatch.setattr(export_formats, "run_browser_command", lambda command, timeout: fake(command, timeout=timeout))
    return fake


def test_svg_export_is_standalone_and_styled(chart, monkeypatch):
    monkeypatch.setattr(export_formats, "settings", replace(settings, png_theme="dark"))

    message = export_svg(chart)

    svg = chart.with_suffix(".svg").read_text(encoding="utf-8")
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "<style>" in svg and svgcharts.DARK_VARS in svg
    assert "legend-value" in svg
    assert message.startswith("saved sales-revenue-bar.svg,")


def test_svg_export_refuses_tampered_chart(workspace):
    folder = workspace / "charts"
    folder.mkdir()
    page = folder / "bad.html"
    page.write_text(
        svgcharts.html_page("Title", "Source", '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'),
        encoding="utf-8",
    )

    with pytest.raises(ExportError, match="elements"):
        export_svg(page)
    assert not page.with_suffix(".svg").exists()


def test_pdf_export_prints_a_fixed_theme_page(chart, browser, monkeypatch):
    monkeypatch.setattr(export_formats, "settings", replace(settings, png_theme="dark"))

    message = export_pdf(chart)

    assert chart.with_suffix(".pdf").read_bytes() == browser.output
    assert any(part.startswith("--print-to-pdf=") for part in browser.command)
    assert "--no-pdf-header-footer" in browser.command
    assert svgcharts.DARK_VARS in browser.page_html.split("</style>")[0].rsplit(":root {", 1)[1]
    assert message.startswith("saved sales-revenue-bar.pdf,")


def test_pdf_timeout_becomes_an_export_error(chart, browser):
    browser.error = subprocess.TimeoutExpired("browser", 30)

    with pytest.raises(ExportError, match="did not finish"):
        export_pdf(chart)


def test_pdf_rejects_missing_or_invalid_output(chart, browser):
    browser.output = b"not pdf"

    with pytest.raises(ExportError, match="valid PDF"):
        export_pdf(chart)
    assert not chart.with_suffix(".pdf").exists()


def test_pdf_refuses_tampered_chart(chart, browser):
    chart.write_text(
        svgcharts.html_page("Title", "Source", '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'),
        encoding="utf-8",
    )

    with pytest.raises(ExportError):
        export_pdf(chart)
    assert browser.command == []
