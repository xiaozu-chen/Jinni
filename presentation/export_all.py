from __future__ import annotations

import presentation.export_formats as export_formats
import presentation.export_png as export_png
from presentation.export_png import ExportError
from tools.workspace import CHART_DIR, WORKSPACE

def _exporters():
    return {
        "png": export_png.export_chart,
        "svg": export_formats.export_svg,
        "pdf": export_formats.export_pdf,
    }


def export_all(format_name: str = "all") -> str:
    """Export every in-workspace HTML chart in one or all supported formats."""
    exporters = _exporters()
    if format_name not in (*exporters, "all"):
        raise ValueError("format must be png, svg, pdf, or all")
    folder = (WORKSPACE / CHART_DIR).resolve()
    if not folder.is_dir():
        return "no charts found"
    pages = [
        path for path in sorted(folder.glob("*.html"))
        if path.is_file() and path.resolve().is_relative_to(folder)
    ]
    if not pages:
        return "no charts found"

    formats = exporters if format_name == "all" else {format_name: exporters[format_name]}
    saved, failures = [], []
    for page in pages:
        for name, exporter in formats.items():
            try:
                saved.append(f"{page.stem}.{name}")
                exporter(page)
            except (ExportError, OSError, ValueError) as e:
                failures.append(f"{page.name} ({name}): {e}")
                if saved and saved[-1] == f"{page.stem}.{name}":
                    saved.pop()

    lines = [f"exported {len(saved)} file(s) from {len(pages)} chart(s)"]
    lines.extend(f"saved: {name}" for name in saved)
    lines.extend(f"failed: {failure}" for failure in failures)
    return "\n".join(lines)
