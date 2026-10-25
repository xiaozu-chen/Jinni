import struct
import subprocess
from pathlib import Path

import pytest

import export_png
import svgcharts
from export_png import (
    ExportError, build_command, export_chart, find_browser, parse_export_options, png_size, render_png,
)
from tools.charts import make_chart

MAGIC = b"\x89PNG\r\n\x1a\n"


def fake_png(width=1280, height=720, padding=2000):
    header = b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return MAGIC + header + b"\x00" * padding


class FakeBrowser:
    """Stands in for subprocess.run: writes a PNG where --screenshot= says, and remembers what it saw."""

    def __init__(self):
        self.png, self.error, self.writes = fake_png(), None, True
        self.command, self.page_html, self.kwargs = [], "", {}

    def __call__(self, command, **kwargs):
        self.command, self.kwargs = command, kwargs
        if self.error:
            raise self.error
        profile = next(a for a in command if a.startswith("--user-data-dir="))[len("--user-data-dir="):]
        self.page_html = (Path(profile).parent / "chart.html").read_text(encoding="utf-8")
        if self.writes:
            target = next(a for a in command if a.startswith("--screenshot="))[len("--screenshot="):]
            Path(target).write_bytes(self.png)
        return subprocess.CompletedProcess(command, 0, b"", b"some browser noise")


@pytest.fixture
def browser(monkeypatch):
    fake = FakeBrowser()
    monkeypatch.setattr(export_png, "find_browser", lambda configured="": "fake-browser")
    monkeypatch.setattr(export_png.subprocess, "run", fake)
    return fake


def test_png_size_reads_the_header():
    assert png_size(fake_png(300, 200)) == (300, 200)


@pytest.mark.parametrize("data", [
    b"", b"not a png", MAGIC, fake_png(0, 10), fake_png(10, 0)[:30],
    b"\x89PNG" + b"x" * 40, fake_png(100_000, 10),
])
def test_png_size_rejects_garbage(data):
    assert png_size(data) is None


def test_command_has_the_flags_that_matter(tmp_path):
    page, shot, profile = tmp_path / "c.html", tmp_path / "s.png", tmp_path / "profile"
    command = build_command("browser", page, shot, profile, 1280, 720, 2.0)

    assert command[0] == "browser"
    assert "--headless=new" in command
    assert f"--user-data-dir={profile}" in command
    assert f"--screenshot={shot}" in command
    assert "--window-size=1280,720" in command
    assert "--force-device-scale-factor=2" in command
    assert command[-1] == page.as_uri()
    assert not any("sandbox" in part for part in command)


def test_a_configured_browser_path_wins(tmp_path):
    exe = tmp_path / "my-browser.exe"
    exe.write_text("")
    assert find_browser(str(exe)) == str(exe)
    assert find_browser(str(tmp_path / "missing.exe")) is None


def test_no_browser_found(monkeypatch):
    monkeypatch.setattr(export_png, "CANDIDATES", ())
    monkeypatch.setattr(export_png.shutil, "which", lambda name: None)
    assert find_browser("") is None


@pytest.mark.parametrize(("text", "expected"), [
    ("", ("", None, None, None)),
    ("dark", ("", "dark", None, None)),
    ("sales dark 1920x1080", ("sales", "dark", 1920, 1080)),
    ("1280x720 sales", ("sales", None, 1280, 720)),
])
def test_parse_png_options(text, expected):
    assert parse_export_options(text) == expected


@pytest.mark.parametrize("text", [
    "dark light", "sales other", "800x600 1200x800", "319x720", "1280x4321", "12xwide",
])
def test_parse_png_options_rejects_invalid_values(text):
    with pytest.raises(ValueError):
        parse_export_options(text)


def test_render_saves_a_verified_png(browser, tmp_path):
    out = tmp_path / "chart.png"
    width, height, size = render_png("<html></html>", out)
    assert (width, height) == (1280, 720)
    assert out.read_bytes() == browser.png
    assert size == len(browser.png)


def test_render_uses_a_throwaway_profile_and_a_timeout(browser, tmp_path):
    render_png("<html></html>", tmp_path / "chart.png")
    profile = next(a for a in browser.command if a.startswith("--user-data-dir="))
    assert "jinni-png-" in profile
    assert browser.kwargs["timeout"] > 0
    assert not browser.kwargs.get("shell", False)


def test_render_without_a_browser_explains_itself(monkeypatch, tmp_path):
    monkeypatch.setattr(export_png, "find_browser", lambda configured="": None)
    with pytest.raises(ExportError, match="browser_path"):
        render_png("<html></html>", tmp_path / "chart.png")


def test_render_timeout_becomes_an_export_error(browser, tmp_path):
    browser.error = subprocess.TimeoutExpired("browser", 30)
    with pytest.raises(ExportError, match="did not finish"):
        render_png("<html></html>", tmp_path / "chart.png")


def test_render_start_failure_becomes_an_export_error(browser, tmp_path):
    browser.error = FileNotFoundError("gone")
    with pytest.raises(ExportError, match="could not start"):
        render_png("<html></html>", tmp_path / "chart.png")


def test_render_without_output_is_an_error(browser, tmp_path):
    browser.writes = False
    out = tmp_path / "chart.png"
    with pytest.raises(ExportError, match="did not produce"):
        render_png("<html></html>", out)
    assert not out.exists()


def test_render_with_garbage_output_is_an_error(browser, tmp_path):
    browser.png = b"definitely not a png"
    out = tmp_path / "chart.png"
    with pytest.raises(ExportError, match="did not produce"):
        render_png("<html></html>", out)
    assert not out.exists()


def test_export_chart_renders_a_forced_theme_and_saves_next_to_the_page(browser, workspace):
    (workspace / "s.csv").write_text("m,v\na,1\nb,2\n", encoding="utf-8")
    assert make_chart("s.csv", "m", "v").startswith("Saved")
    page = workspace / "charts" / "s-v-bar.html"

    message = export_chart(page)

    assert (workspace / "charts" / "s-v-bar.png").read_bytes() == browser.png
    assert "1280x720" in message
    assert "default-src 'none'" in browser.page_html
    assert svgcharts.LIGHT_VARS in browser.page_html.split("</style>")[0].rsplit(":root {", 1)[1]


def test_export_chart_accepts_a_theme_and_custom_viewport(browser, workspace):
    (workspace / "s.csv").write_text("m,v\na,1\nb,2\n", encoding="utf-8")
    make_chart("s.csv", "m", "v")
    page = workspace / "charts" / "s-v-bar.html"

    message = export_chart(page, "dark", 1920, 1080)

    assert "--window-size=1920,1080" in browser.command
    assert svgcharts.DARK_VARS in browser.page_html.split("</style>")[0].rsplit(":root {", 1)[1]
    assert "1280x720" in message


def test_export_chart_rejects_an_invalid_custom_viewport(browser, workspace):
    (workspace / "s.csv").write_text("m,v\na,1\nb,2\n", encoding="utf-8")
    make_chart("s.csv", "m", "v")
    page = workspace / "charts" / "s-v-bar.html"

    with pytest.raises(ExportError, match="PNG size"):
        export_chart(page, width=319, height=720)
    assert browser.command == []


def test_export_chart_refuses_a_tampered_chart(browser, workspace):
    charts = workspace / "charts"
    charts.mkdir()
    evil = svgcharts.html_page("T", "S", '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>')
    (charts / "evil.html").write_text(evil, encoding="utf-8")

    with pytest.raises(ExportError):
        export_chart(charts / "evil.html")
    assert browser.command == []
