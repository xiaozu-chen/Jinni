import presentation.export_all as export_all
from presentation.export_png import ExportError


def test_export_all_runs_each_format_for_every_chart(workspace, monkeypatch):
    folder = workspace / "charts"
    folder.mkdir()
    pages = [folder / "a.html", folder / "b.html"]
    for page in pages:
        page.write_text("page", encoding="utf-8")
    calls = []
    monkeypatch.setattr(export_all, "WORKSPACE", workspace)
    monkeypatch.setattr(export_all.export_png, "export_chart", lambda page: calls.append((page.name, "png")))
    monkeypatch.setattr(export_all.export_formats, "export_svg", lambda page: calls.append((page.name, "svg")))
    monkeypatch.setattr(export_all.export_formats, "export_pdf", lambda page: calls.append((page.name, "pdf")))

    result = export_all.export_all()

    assert calls == [(page.name, fmt) for page in pages for fmt in ("png", "svg", "pdf")]
    assert "exported 6 file(s) from 2 chart(s)" in result


def test_export_all_continues_after_a_chart_failure(workspace, monkeypatch):
    folder = workspace / "charts"
    folder.mkdir()
    for name in ("bad.html", "good.html"):
        (folder / name).write_text("page", encoding="utf-8")
    saved = []

    def exporter(page):
        if page.stem == "bad":
            raise ExportError("unsafe chart")
        saved.append(page.name)

    monkeypatch.setattr(export_all, "WORKSPACE", workspace)
    monkeypatch.setattr(export_all.export_png, "export_chart", exporter)

    result = export_all.export_all("png")

    assert saved == ["good.html"]
    assert "failed: bad.html (png): unsafe chart" in result
    assert "exported 1 file(s) from 2 chart(s)" in result


def test_export_all_requires_a_known_format():
    try:
        export_all.export_all("docx")
    except ValueError as error:
        assert "format must be" in str(error)
    else:
        raise AssertionError("an unknown format should be refused")


def test_export_all_reports_an_empty_chart_folder(workspace, monkeypatch):
    monkeypatch.setattr(export_all, "WORKSPACE", workspace)
    assert export_all.export_all() == "no charts found"
