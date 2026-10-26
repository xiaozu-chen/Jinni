import csv
import io
import logging
import math
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

import svgcharts
from chart_records import record_genuine_chart

from .registry import tool
from .provenance import read_csv_provenance
from .workspace import CHART_DIR, safe_path, was_written

log = logging.getLogger("jinni.tools.charts")

MAX_ROWS = 50
MAX_CSV_BYTES = 200_000
MAX_XLSX_BYTES = 2_000_000
MAX_XLSX_XML_BYTES = 2_000_000
MAX_SERIES = 6
KINDS = ("bar", "stacked", "line", "pie", "donut")
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column_index(reference: str) -> int:
    match = re.fullmatch(r"([A-Z]+)\d+", reference)
    if not match:
        raise ValueError("the Excel file contains an invalid cell reference")
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - ord("A") + 1
    return number - 1


def _xlsx_csv(path) -> str:
    """Read the first worksheet of a bounded .xlsx file without third-party packages."""
    if path.stat().st_size > MAX_XLSX_BYTES:
        raise ValueError(f"Excel file is too large to chart (limit {MAX_XLSX_BYTES // 1000} KB)")
    try:
        with zipfile.ZipFile(path) as book:
            if sum(info.file_size for info in book.infolist()) > MAX_XLSX_BYTES * 4:
                raise ValueError("the Excel workbook expands beyond the allowed size")

            def read_xml(name: str):
                info = book.getinfo(name)
                if info.file_size > MAX_XLSX_XML_BYTES:
                    raise ValueError("an Excel worksheet is too large to chart")
                return ET.fromstring(book.read(name))

            workbook = read_xml("xl/workbook.xml")
            relation_doc = read_xml("xl/_rels/workbook.xml.rels")
            relations = {
                relation.get("Id"): relation.get("Target")
                for relation in relation_doc.findall(f"{{{PKG_REL_NS}}}Relationship")
            }
            sheet = workbook.find(f"{{{MAIN_NS}}}sheets/{{{MAIN_NS}}}sheet")
            if sheet is None:
                raise ValueError("the Excel workbook has no worksheets")
            relation_id = sheet.get(f"{{{REL_NS}}}id")
            target = relations.get(relation_id)
            if not target:
                raise ValueError("the first Excel worksheet could not be opened")
            sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            shared = []
            if "xl/sharedStrings.xml" in book.namelist():
                shared_doc = read_xml("xl/sharedStrings.xml")
                shared = ["".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t"))
                          for item in shared_doc.findall(f"{{{MAIN_NS}}}si")]
            worksheet = read_xml(sheet_path)
            data_rows = worksheet.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row")
            if len(data_rows) > MAX_ROWS + 1:
                raise ValueError(f"too many rows (the limit is {MAX_ROWS}). Use a smaller file.")
            output = io.StringIO()
            writer = csv.writer(output)
            for row in data_rows:
                cells: dict[int, str] = {}
                for cell in row.findall(f"{{{MAIN_NS}}}c"):
                    index = _column_index(cell.get("r", ""))
                    cell_type = cell.get("t", "")
                    value = cell.find(f"{{{MAIN_NS}}}v")
                    if cell_type == "inlineStr":
                        text = "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
                    elif value is None:
                        if cell.find(f"{{{MAIN_NS}}}f") is not None:
                            raise ValueError("an Excel formula has no saved result; recalculate the workbook first")
                        text = ""
                    elif cell_type == "s":
                        string_index = int(value.text or "0")
                        if string_index >= len(shared):
                            raise ValueError("the Excel workbook has a broken shared-string reference")
                        text = shared[string_index]
                    else:
                        text = value.text or ""
                    cells[index] = text
                writer.writerow([cells.get(index, "") for index in range(max(cells, default=-1) + 1)])
            return output.getvalue()
    except zipfile.BadZipFile:
        raise ValueError("the file is not a valid .xlsx workbook") from None
    except KeyError as e:
        raise ValueError(f"the Excel workbook is missing {e.args[0]}") from None
    except ET.ParseError:
        raise ValueError("the Excel workbook contains invalid XML") from None


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
    description="Make a bar, stacked bar, line, pie or donut chart from CSV or Excel (.xlsx) data in the workspace. Use secondary_y_column for a second line-chart scale. The page can be viewed with /open.",
    params={
        "file": "CSV or Excel .xlsx path relative to the workspace, like sales.csv or sales.xlsx. The first row of the first sheet must contain column names.",
        "x_column": "Name of the column for the labels (the horizontal axis, or the pie slice names).",
        "y_column": "Name of the numeric column, or comma-separated series such as 'sales,returns'.",
        "kind": "'bar', 'stacked', 'line', 'pie' or 'donut'. Use 'bar' by default; use pie or donut for parts of a whole.",
        "title": "A short chart title. Optional.",
        "secondary_y_column": "Optional numeric column or comma-separated columns plotted on a second line-chart scale.",
    },
    approval=True,
)
def make_chart(file: str, x_column: str, y_column: str, kind: str = "bar", title: str = "",
               secondary_y_column: str = "") -> str:
    try:
        if kind not in KINDS:
            return f"Error: kind must be one of {', '.join(KINDS)}, not '{kind}'."
        y_columns = split_columns(y_column)
        secondary_columns = split_columns(secondary_y_column)
        if not y_columns:
            return "Error: y_column must name at least one column."
        if kind in ("pie", "donut") and (len(y_columns) != 1 or secondary_columns):
            return f"Error: a {kind} chart needs exactly one y_column."
        if secondary_columns and kind != "line":
            return "Error: secondary_y_column can only be used with a line chart."
        if set(y_columns) & set(secondary_columns):
            return "Error: primary and secondary y columns must be different."
        if kind == "stacked" and len(y_columns) < 2:
            return "Error: a stacked bar chart needs at least two y columns."
        if len(y_columns) + len(secondary_columns) > MAX_SERIES:
            return f"Error: at most {MAX_SERIES} columns can be charted together."

        source = safe_path(file)
        if source.suffix.lower() == ".xlsx":
            table = _xlsx_csv(source)
        elif source.suffix.lower() == ".csv":
            if source.stat().st_size > MAX_CSV_BYTES:
                return f"Error: '{file}' is too large to chart (limit {MAX_CSV_BYTES // 1000} KB)."
            table = source.read_text(encoding="utf-8-sig")
        else:
            return "Error: use a .csv or .xlsx file. Older .xls workbooks are not supported."
        labels, all_series = load_table(table, x_column, [*y_columns, *secondary_columns])
        series = {name: all_series[name] for name in y_columns}
        secondary = {name: all_series[name] for name in secondary_columns}
        provenance = read_csv_provenance(source) if source.suffix.lower() == ".csv" else None
        snippet_source = (
            source.name.startswith("search-snippets-")
            or bool(provenance and provenance.get("kind") == "snippet")
        )
        typed_by_model = (
            bool(provenance and provenance.get("kind") in {"typed", "snippet"})
            or (was_written(source) and provenance is None)
        )

        names = ", ".join([*y_columns, *secondary_columns])
        title = (title or f"{names} by {x_column}")[:120]
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{source.stem}-{names}-{kind}").strip("-").lower()[:60] or "chart"
        if kind == "pie":
            svg = svgcharts.pie_chart(labels, series[y_columns[0]], title)
        elif kind == "donut":
            svg = svgcharts.donut_chart(labels, series[y_columns[0]], title)
        elif kind == "stacked":
            svg = svgcharts.stacked_bar_chart(labels, series, title, x_column, names)
        elif kind == "bar":
            svg = svgcharts.bar_chart(labels, series, title, x_column, names)
        else:
            svg = svgcharts.line_chart(labels, series, title, x_column, ", ".join(y_columns), secondary)

        if snippet_source:
            fetched = provenance["fetched_at"][:10] if provenance else "date unavailable"
            query = str((provenance or {}).get("query") or "query unavailable")[:80]
            sources = (provenance or {}).get("sources") or []
            source_count = len(sources) if isinstance(sources, list) else 0
            subtitle = f"Source: search snippets for {query}, fetched {fetched} · {source_count} source(s) · {len(labels)} rows · numbers unverified"
        elif provenance and provenance.get("kind") == "typed":
            created = provenance["fetched_at"][:10]
            subtitle = f"Source: typed by Jinni, recorded {created} · {len(labels)} rows"
        elif provenance:
            fetched = provenance["fetched_at"][:10]
            subtitle = f"Source: {provenance['source_url']}, fetched {fetched} · {len(labels)} rows"
        else:
            subtitle = f"Source: {file} · {len(labels)} rows"
        if typed_by_model and not snippet_source:
            subtitle += " · numbers unverified"
        page = svgcharts.html_page(title, subtitle, svg)

        out = safe_path(f"{CHART_DIR}/{slug}.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        try:
            record_genuine_chart(out, page)
            record_note = ""
        except OSError:
            record_note = " The integrity record could not be saved, so /open will use its structural check."
        note = (
            " Note: these values came from search snippets and need checking against their source pages."
            if snippet_source else
            " Note: Jinni typed this data, so tell the user its numbers are unverified."
            if typed_by_model else ""
        )
        return f"Saved the chart to {CHART_DIR}/{slug}.html ({len(labels)} rows). Tell the user to type /open to view it.{note}{record_note}"
    except FileNotFoundError:
        return f"Error: '{file}' was not found in the workspace."
    except Exception as e:
        log.exception("make_chart failed for %s", file)
        return f"Error: {e}"
