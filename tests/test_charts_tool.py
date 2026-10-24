import os

import tools
from tools.charts import make_chart
from tools.workspace import find_chart
from tools.files import write_file

CSV = "month,sales,note\nJan,10,a\nFeb,25.5,b\nMar,-3,c\n"
MULTI = "month,sales,returns\nJan,120,8\nFeb,135,11\nMar,150,9\n"


def put(workspace, name, text):
    (workspace / name).write_text(text, encoding="utf-8")


def test_creates_a_bar_chart_page(workspace):
    put(workspace, "sales.csv", CSV)
    result = make_chart("sales.csv", "month", "sales", "bar", "Sales")
    assert result.startswith("Saved")
    page = (workspace / "charts" / "sales-sales-bar.html").read_text(encoding="utf-8")
    assert "<svg" in page and "Sales" in page


def test_creates_a_line_chart_page(workspace):
    put(workspace, "sales.csv", CSV)
    assert make_chart("sales.csv", "month", "sales", "line").startswith("Saved")
    assert (workspace / "charts" / "sales-sales-line.html").exists()


def test_unknown_column_lists_the_real_ones(workspace):
    put(workspace, "sales.csv", CSV)
    result = make_chart("sales.csv", "month", "revenue")
    assert result.startswith("Error")
    assert "month, sales, note" in result


def test_non_number_names_the_row(workspace):
    put(workspace, "bad.csv", "month,sales\nJan,10\nFeb,abc\n")
    result = make_chart("bad.csv", "month", "sales")
    assert result.startswith("Error")
    assert "row 3" in result


def test_bad_kind_is_refused(workspace):
    put(workspace, "sales.csv", CSV)
    assert make_chart("sales.csv", "month", "sales", "donut").startswith("Error")



def test_row_limit(workspace):
    rows = "".join(f"r{i},{i}\n" for i in range(51))
    put(workspace, "big.csv", "k,v\n" + rows)
    assert "too many rows" in make_chart("big.csv", "k", "v")

    put(workspace, "ok.csv", "k,v\n" + rows.split("\n", 1)[1])
    assert make_chart("ok.csv", "k", "v").startswith("Saved")


def test_outside_the_workspace_is_refused(workspace):
    assert make_chart("../sales.csv", "a", "b").startswith("Error")


def test_missing_file(workspace):
    assert "not found" in make_chart("nope.csv", "a", "b")


def test_csv_with_a_bom_works(workspace):
    (workspace / "excel.csv").write_bytes(b"\xef\xbb\xbf" + CSV.encode("utf-8"))
    assert make_chart("excel.csv", "month", "sales").startswith("Saved")


def test_chart_tool_needs_approval_and_is_not_rememberable():
    assert "make_chart" in tools.NEEDS_APPROVAL
    assert "make_chart" not in tools.REMEMBERABLE


def test_find_chart_returns_newest_or_named(workspace):
    assert find_chart() is None
    charts = workspace / "charts"
    charts.mkdir()
    old, new = charts / "old.html", charts / "new.html"
    old.write_text("x")
    new.write_text("x")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    assert find_chart() == new
    assert find_chart("old") == old
    assert find_chart("nope") is None


def test_chart_of_a_file_the_model_wrote_is_flagged(workspace):
    write_file("typed.csv", "k,v\na,1\nb,2\n")
    result = make_chart("typed.csv", "k", "v")
    page = (workspace / "charts" / "typed-v-bar.html").read_text(encoding="utf-8")
    assert "unverified" in result
    assert "unverified" in page


def test_chart_of_a_user_file_is_not_flagged(workspace):
    put(workspace, "mine.csv", "k,v\na,1\n")
    assert "unverified" not in make_chart("mine.csv", "k", "v")


def test_several_columns_make_a_multi_series_chart(workspace):
    put(workspace, "m.csv", MULTI)
    assert make_chart("m.csv", "month", "sales, returns", "line").startswith("Saved")
    page = (workspace / "charts" / "m-sales-returns-line.html").read_text(encoding="utf-8")
    assert page.count("<polyline") == 2


def test_pie_chart_page(workspace):
    put(workspace, "p.csv", "fruit,count\napple,5\npear,3\nfig,2\n")
    assert make_chart("p.csv", "fruit", "count", "pie").startswith("Saved")
    page = (workspace / "charts" / "p-count-pie.html").read_text(encoding="utf-8")
    assert page.count("<path") == 3


def test_pie_with_several_columns_is_refused(workspace):
    put(workspace, "m.csv", MULTI)
    assert make_chart("m.csv", "month", "sales,returns", "pie").startswith("Error")


def test_pie_with_negative_numbers_is_refused(workspace):
    put(workspace, "sales.csv", CSV)
    result = make_chart("sales.csv", "month", "sales", "pie")
    assert result.startswith("Error")
    assert "pie" in result.lower()


def test_too_many_series_are_refused(workspace):
    columns = [f"c{i}" for i in range(8)]
    put(workspace, "wide.csv", "k," + ",".join(columns) + "\na," + ",".join("1" for _ in columns) + "\n")
    assert make_chart("wide.csv", "k", ",".join(columns)).startswith("Error")


def test_an_unknown_second_column_lists_the_real_ones(workspace):
    put(workspace, "m.csv", MULTI)
    result = make_chart("m.csv", "month", "sales,profit")
    assert "profit" in result
    assert "month, sales, returns" in result