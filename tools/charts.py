import csv
import io
import math
import re

import svgcharts

from .registry import tool
from .workspace import CHART_DIR, safe_path

MAX_ROWS = 50
MAX_CSV_BYTES = 200_000
KINDS = ("bar", "line")


def load_series(text: str, x_column: str, y_column: str) -> tuple[list[str], list[float]]:
    reader = csv.DictReader(io.StringIO(text))
    names = reader.fieldnames or []
    for wanted in (x_column, y_column):
        if wanted not in names:
            raise ValueError(f"column '{wanted}' not found. Available columns: {', '.join(names) or '(none)'}")

    labels: list[str] = []
    values: list[float] = []
    for row in reader:
        raw = (row.get(y_column) or "").strip().replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"row {reader.line_num}: '{raw}' in column '{y_column}' is not a number") from None
        if not math.isfinite(value):
            raise ValueError(f"row {reader.line_num}: '{raw}' is not a usable number")
        labels.append((row.get(x_column) or "").strip())
        values.append(value)
        if len(values) > MAX_ROWS:
            raise ValueError(f"too many rows (the limit is {MAX_ROWS}). Use a smaller file.")
    if not values:
        raise ValueError("the file has no data rows")
    return labels, values


@tool(
    description="Make a bar or line chart from two columns of a CSV file in the workspace and save it as an HTML page. The user can then type /open to view it. If you do not know the column names, read the file first.",
    params={
        "file": "CSV file path relative to the workspace, like sales.csv. The first row must be the column names.",
        "x_column": "Name of the column for the labels (the horizontal axis).",
        "y_column": "Name of the column with the numbers to plot.",
        "kind": "Either 'bar' or 'line'. Use 'bar' unless the data is a trend over time.",
        "title": "A short chart title. Optional.",
    },
    approval=True,
)
def make_chart(file: str, x_column: str, y_column: str, kind: str = "bar", title: str = "") -> str:
    try:
        if kind not in KINDS:
            return f"Error: kind must be 'bar' or 'line', not '{kind}'."
        source = safe_path(file)
        if source.stat().st_size > MAX_CSV_BYTES:
            return f"Error: '{file}' is too large to chart (limit {MAX_CSV_BYTES // 1000} KB)."
        labels, values = load_series(source.read_text(encoding="utf-8-sig"), x_column, y_column)

        title = (title or f"{y_column} by {x_column}")[:120]
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{source.stem}-{y_column}-{kind}").strip("-").lower()[:60] or "chart"
        draw = svgcharts.bar_chart if kind == "bar" else svgcharts.line_chart
        page = svgcharts.html_page(
            title, f"Source: {file} · {len(values)} rows", draw(labels, values, title, x_column, y_column)
        )

        out = safe_path(f"{CHART_DIR}/{slug}.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        return f"Saved the chart to {CHART_DIR}/{slug}.html ({len(values)} rows). Tell the user to type /open to view it."
    except FileNotFoundError:
        return f"Error: '{file}' was not found in the workspace."
    except Exception as e:
        return f"Error: {e}"