import csv
import io
import math
import re

import svgcharts

from .registry import tool
from .workspace import CHART_DIR, safe_path, was_written

MAX_ROWS = 50
MAX_CSV_BYTES = 200_000
MAX_SERIES = 6
KINDS = ("bar", "line", "pie")


def split_columns(text: str) -> list[str]:
    names: list[str] = []
    for part in text.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def load_table(text: str, x_column: str, y_columns: list[str]) -> tuple[list[str], dict[str, list[float]]]:
    reader = csv.DictReader(io.StringIO(text))
    names = reader.fieldnames or []
    for wanted in [x_column, *y_columns]:
        if wanted not in names:
            raise ValueError(f"column '{wanted}' not found. Available columns: {', '.join(names) or '(none)'}")

    labels: list[str] = []
    series: dict[str, list[float]] = {name: [] for name in y_columns}
    for row in reader:
        for name in y_columns:
            raw = (row.get(name) or "").strip().replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                raise ValueError(f"row {reader.line_num}: '{raw}' in column '{name}' is not a number") from None
            if not math.isfinite(value):
                raise ValueError(f"row {reader.line_num}: '{raw}' is not a usable number")
            series[name].append(value)
        labels.append((row.get(x_column) or "").strip())
        if len(labels) > MAX_ROWS:
            raise ValueError(f"too many rows (the limit is {MAX_ROWS}). Use a smaller file.")
    if not labels:
        raise ValueError("the file has no data rows")
    return labels, series


@tool(
    description="Make a bar, line or pie chart from columns of a CSV file in the workspace and save it as an HTML page. The user can then type /open to view it. If you do not know the column names, read the file first.",
    params={
        "file": "CSV file path relative to the workspace, like sales.csv. The first row must be the column names.",
        "x_column": "Name of the column for the labels (the horizontal axis, or the pie slice names).",
        "y_column": "Name of the column with the numbers to plot. For several series give comma-separated names like 'sales,returns' (bar or line only, at most 6).",
        "kind": "'bar', 'line' or 'pie'. Use 'bar' by default, 'line' for a trend over time, 'pie' only for parts of a whole.",
        "title": "A short chart title. Optional.",
    },
    approval=True,
)
def make_chart(file: str, x_column: str, y_column: str, kind: str = "bar", title: str = "") -> str:
    try:
        if kind not in KINDS:
            return f"Error: kind must be 'bar', 'line' or 'pie', not '{kind}'."
        y_columns = split_columns(y_column)
        if not y_columns:
            return "Error: y_column must name at least one column."
        if kind == "pie" and len(y_columns) != 1:
            return "Error: a pie chart needs exactly one y_column."
        if len(y_columns) > MAX_SERIES:
            return f"Error: at most {MAX_SERIES} columns can be charted together."

        source = safe_path(file)
        if source.stat().st_size > MAX_CSV_BYTES:
            return f"Error: '{file}' is too large to chart (limit {MAX_CSV_BYTES // 1000} KB)."
        labels, series = load_table(source.read_text(encoding="utf-8-sig"), x_column, y_columns)
        typed_by_model = was_written(source)

        names = ", ".join(y_columns)
        title = (title or f"{names} by {x_column}")[:120]
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{source.stem}-{y_column}-{kind}").strip("-").lower()[:60] or "chart"
        if kind == "pie":
            svg = svgcharts.pie_chart(labels, series[y_columns[0]], title)
        elif kind == "bar":
            svg = svgcharts.bar_chart(labels, series, title, x_column, names)
        else:
            svg = svgcharts.line_chart(labels, series, title, x_column, names)

        subtitle = f"Source: {file} · {len(labels)} rows"
        if typed_by_model:
            subtitle += " · typed by Jinni this session, numbers unverified"
        page = svgcharts.html_page(title, subtitle, svg)

        out = safe_path(f"{CHART_DIR}/{slug}.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        note = " Note: this CSV was typed by Jinni itself this session, so tell the user its numbers are unverified." if typed_by_model else ""
        return f"Saved the chart to {CHART_DIR}/{slug}.html ({len(labels)} rows). Tell the user to type /open to view it.{note}"
    except FileNotFoundError:
        return f"Error: '{file}' was not found in the workspace."
    except Exception as e:
        return f"Error: {e}"
