import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from html import escape, unescape
from string import Template

WIDTH, HEIGHT = 640, 360
LEFT, RIGHT, TOP, BOTTOM = 76, 24, 24, 72
MAX_SERIES = 8
PIE_R = 130
PIE_CX, PIE_CY = 190, HEIGHT // 2

SVG_NS = "{http://www.w3.org/2000/svg}"
SVG_TAGS = {"svg", "title", "line", "text", "rect", "circle", "polyline", "path"}
SVG_ATTRS = {"viewBox", "role", "aria-label", "class", "x", "y", "x1", "y1", "x2", "y2",
             "width", "height", "rx", "cx", "cy", "r", "d", "points", "transform", "text-anchor"}
MAX_SVG_CHARS = 500_000

_H1 = re.compile(r"<h1>(.*?)</h1>", re.S)
_SUB = re.compile(r'<p class="sub">(.*?)</p>', re.S)


LIGHT_VARS = ("--bg:#ffffff; --fg:#1f2328; --muted:#6b7280; --grid:#e5e7eb; "
              "--c0:#2563eb; --c1:#d97706; --c2:#059669; --c3:#db2777; "
              "--c4:#7c3aed; --c5:#0891b2; --c6:#a16207; --c7:#64748b;")
DARK_VARS = ("--bg:#111418; --fg:#e6e8eb; --muted:#9aa4b2; --grid:#2a2f37; "
             "--c0:#60a5fa; --c1:#fbbf24; --c2:#34d399; --c3:#f472b6; "
             "--c4:#a78bfa; --c5:#22d3ee; --c6:#facc15; --c7:#94a3b8;")

SVG_EXPORT_CSS = """\
:root { $vars }
.s0 { --c: var(--c0); } .s1 { --c: var(--c1); } .s2 { --c: var(--c2); } .s3 { --c: var(--c3); }
.s4 { --c: var(--c4); } .s5 { --c: var(--c5); } .s6 { --c: var(--c6); } .s7 { --c: var(--c7); }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--muted); stroke-width: 1; }
.tick, .xlabel, .axis-title { fill: var(--muted); font-size: 12px; }
.value { fill: var(--fg); font-size: 11px; }
.bar, .dot, .swatch, .slice { fill: var(--c); }
.slice { stroke: var(--bg); stroke-width: 2; }
.line { fill: none; stroke: var(--c); stroke-width: 2.5; stroke-linejoin: round; }
.legend { fill: var(--fg); font-size: 12px; }
.legend-value { fill: var(--muted); font-size: 12px; }
"""

EXPORT_CSS = """/* export layout */
  html, body { height: 100%; }
  body { padding: 20px 28px; box-sizing: border-box; overflow: hidden; }
  main { max-width: none; height: 100%; display: flex; flex-direction: column; }
  svg { flex: 1; min-height: 0; width: 100%; height: auto; }
  h1 { font-size: 1.6rem; }
  p.sub { font-size: 1rem; }
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
  :root { $light_vars --c: var(--c0); color-scheme: light dark; }
  @media (prefers-color-scheme: dark) {
    :root { $dark_vars }
  }
  body { margin:0; padding:24px; background:var(--bg); color:var(--fg); font-family: system-ui, "Segoe UI", sans-serif; }
  main { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 1.25rem; font-weight: 600; margin: 0 0 4px; }
  p.sub { color: var(--muted); margin: 0 0 16px; font-size: .9rem; }
  svg { width: 100%; height: auto; }
  .s0 { --c: var(--c0); } .s1 { --c: var(--c1); } .s2 { --c: var(--c2); } .s3 { --c: var(--c3); }
  .s4 { --c: var(--c4); } .s5 { --c: var(--c5); } .s6 { --c: var(--c6); } .s7 { --c: var(--c7); }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .axis { stroke: var(--muted); stroke-width: 1; }
  .tick, .xlabel, .axis-title { fill: var(--muted); font-size: 12px; }
  .value { fill: var(--fg); font-size: 11px; }
  .bar, .dot, .swatch, .slice { fill: var(--c); }
  .slice { stroke: var(--bg); stroke-width: 2; }
  .line { fill: none; stroke: var(--c); stroke-width: 2.5; stroke-linejoin: round; }
  .legend { fill: var(--fg); font-size: 12px; }
  .legend-value { fill: var(--muted); font-size: 12px; }
$extra</style>
</head>
<body>
<main>
<h1>$title</h1>
<p class="sub">$subtitle</p>
$svg
</main>
</body>
</html>
"""



def nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    """Round, evenly spaced tick values that cover [low, high]."""
    if high <= low:
        high = low + 1
    raw = (high - low) / max(target - 1, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if step >= raw:
            break
    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    count = round((end - start) / step)
    return [round(start + i * step, 10) for i in range(count + 1)]


def fmt(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 0.01:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.3g}"


def compact(value: float) -> str:
    """1500000000 -> '1.5B', 25000 -> '25K'. Small numbers fall back to fmt()."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= limit:
            text = f"{v / limit:.2f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return fmt(value)


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tip(label: str, name: str, value: float) -> str:
    who = f" · {escape(name)}" if name else ""
    return f"{escape(label)}{who}: {fmt(value)}"


def _as_series(values: Sequence[float] | Mapping[str, Sequence[float]]) -> dict[str, list[float]]:
    if isinstance(values, Mapping):
        return {str(name): [float(v) for v in vs] for name, vs in values.items()}
    return {"": [float(v) for v in values]}


def _legend(names: list[str], width: float) -> tuple[list[str], int]:
    """SVG pieces for a wrapping legend, and the height it needs."""
    parts: list[str] = []
    x, y = float(LEFT), 14
    for i, name in enumerate(names):
        label = _short(name, 20)
        item_w = 18 + 7 * len(label) + 20
        if x > LEFT and x + item_w > LEFT + width:
            x, y = float(LEFT), y + 20
        parts.append(f'<rect class="swatch s{i}" x="{x:.1f}" y="{y - 10}" width="12" height="12" rx="2"/>')
        parts.append(f'<text class="legend" x="{x + 18:.1f}" y="{y}">{escape(label)}</text>')
        x += item_w
    return parts, y + 10


def _xy_svg(kind: str, labels: Sequence[str], values: Sequence[float] | Mapping[str, Sequence[float]],
            title: str, x_title: str, y_title: str) -> str:
    series = _as_series(values)
    labels = [str(label) for label in labels]
    n, m = len(labels), len(series)
    if n == 0 or m == 0 or m > MAX_SERIES or any(len(v) != n for v in series.values()):
        raise ValueError("labels and values must be the same non-zero length, with at most 8 series")
    names = list(series)

    plot_w = WIDTH - LEFT - RIGHT
    legend_parts: list[str] = []
    top = TOP
    if m > 1:
        legend_parts, legend_h = _legend(names, plot_w)
        top = max(TOP, legend_h)
    plot_h = HEIGHT - top - BOTTOM

    everything = [v for vs in series.values() for v in vs]
    if kind == "bar":
        low, high = min(0.0, min(everything)), max(0.0, max(everything))
    else:
        low, high = min(everything), max(everything)
    ticks = nice_ticks(low, high)
    lo, hi = ticks[0], ticks[-1]

    def y_of(v: float) -> float:
        return top + plot_h - (v - lo) / (hi - lo) * plot_h

    slot = plot_w / n
    centers = [LEFT + (i + 0.5) * slot for i in range(n)]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(title)}">',
        f"<title>{escape(title)}</title>",
        *legend_parts,
    ]
    for t in ticks:
        y = y_of(t)
        parts.append(f'<line class="grid" x1="{LEFT}" y1="{y:.1f}" x2="{WIDTH - RIGHT}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{compact(t)}</text>')
    parts.append(f'<line class="axis" x1="{LEFT}" y1="{top}" x2="{LEFT}" y2="{top + plot_h}"/>')
    zero_y = y_of(0) if lo <= 0 <= hi else top + plot_h
    parts.append(f'<line class="axis" x1="{LEFT}" y1="{zero_y:.1f}" x2="{WIDTH - RIGHT}" y2="{zero_y:.1f}"/>')

    if kind == "bar":
        group_w = slot * 0.8
        bar_w = group_w / m
        for j, name in enumerate(names):
            for i, v in enumerate(series[name]):
                x = LEFT + i * slot + (slot - group_w) / 2 + j * bar_w
                y_top, y_bottom = sorted((y_of(v), y_of(0)))
                parts.append(
                    f'<rect class="bar s{j}" x="{x:.1f}" y="{y_top:.1f}" width="{max(bar_w - 1.5, 1):.1f}" '
                    f'height="{y_bottom - y_top:.1f}"><title>{_tip(labels[i], name, v)}</title></rect>'
                )
    else:
        for j, name in enumerate(names):
            vals = series[name]
            points = " ".join(f"{c:.1f},{y_of(v):.1f}" for c, v in zip(centers, vals))
            parts.append(f'<polyline class="line s{j}" points="{points}"/>')
            for c, label, v in zip(centers, labels, vals):
                parts.append(
                    f'<circle class="dot s{j}" cx="{c:.1f}" cy="{y_of(v):.1f}" r="3.5">'
                    f"<title>{_tip(label, name, v)}</title></circle>"
                )

    if m == 1 and n <= 12:
        for c, v in zip(centers, series[names[0]]):
            y = y_of(v) - 6 if v >= 0 else y_of(v) + 14
            parts.append(f'<text class="value" x="{c:.1f}" y="{y:.1f}" text-anchor="middle">{fmt(v)}</text>')

    rotate = n > 8
    limit = 10 if rotate else 14
    label_y = top + plot_h + 18
    for c, label in zip(centers, labels):
        short = _short(label, limit)
        if rotate:
            parts.append(
                f'<text class="xlabel" x="{c:.1f}" y="{label_y}" text-anchor="end" '
                f'transform="rotate(-40 {c:.1f} {label_y})">{escape(short)}</text>'
            )
        else:
            parts.append(f'<text class="xlabel" x="{c:.1f}" y="{label_y}" text-anchor="middle">{escape(short)}</text>')

    mid = top + plot_h / 2
    parts.append(f'<text class="axis-title" x="{LEFT + plot_w / 2:.1f}" y="{HEIGHT - 8}" text-anchor="middle">{escape(_short(x_title, 40))}</text>')
    parts.append(f'<text class="axis-title" x="14" y="{mid:.1f}" text-anchor="middle" transform="rotate(-90 14 {mid:.1f})">{escape(_short(y_title, 36))}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def bar_chart(labels: Sequence[str], values: Sequence[float] | Mapping[str, Sequence[float]],
              title: str, x_title: str, y_title: str) -> str:
    return _xy_svg("bar", labels, values, title, x_title, y_title)


def line_chart(labels: Sequence[str], values: Sequence[float] | Mapping[str, Sequence[float]],
               title: str, x_title: str, y_title: str) -> str:
    return _xy_svg("line", labels, values, title, x_title, y_title)


def pie_chart(labels: Sequence[str], values: Sequence[float], title: str) -> str:
    if not values or len(labels) != len(values):
        raise ValueError("labels and values must be the same non-zero length")
    nums = [float(v) for v in values]
    if not all(math.isfinite(v) for v in nums):
        raise ValueError("a pie chart needs finite numbers")
    if any(v < 0 for v in nums) or not any(v > 0 for v in nums):
        raise ValueError("a pie chart needs numbers that are zero or more, and at least one above zero")

    items = sorted(((str(l), v) for l, v in zip(labels, nums) if v > 0), key=lambda item: -item[1])
    if len(items) > MAX_SERIES:
        rest = items[MAX_SERIES - 1:]
        items = items[: MAX_SERIES - 1] + [("Other", sum(v for _, v in rest))]
    total = sum(v for _, v in items)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(title)}">',
        f"<title>{escape(title)}</title>",
    ]
    if len(items) == 1:
        label, v = items[0]
        parts.append(
            f'<circle class="slice s0" cx="{PIE_CX}" cy="{PIE_CY}" r="{PIE_R}">'
            f"<title>{_tip(label, '', v)}</title></circle>"
        )
    else:
        angle = -math.pi / 2
        for i, (label, v) in enumerate(items):
            end = angle + 2 * math.pi * v / total
            x0, y0 = PIE_CX + PIE_R * math.cos(angle), PIE_CY + PIE_R * math.sin(angle)
            x1, y1 = PIE_CX + PIE_R * math.cos(end), PIE_CY + PIE_R * math.sin(end)
            large = 1 if end - angle > math.pi else 0
            parts.append(
                f'<path class="slice s{i}" d="M {PIE_CX} {PIE_CY} L {x0:.1f} {y0:.1f} '
                f'A {PIE_R} {PIE_R} 0 {large} 1 {x1:.1f} {y1:.1f} Z">'
                f"<title>{_tip(label, '', v)}</title></path>"
            )
            angle = end

    for i, (label, v) in enumerate(items):
        y = 64 + i * 26
        parts.append(f'<rect class="swatch s{i}" x="370" y="{y - 10}" width="12" height="12" rx="2"/>')
        parts.append(f'<text class="legend" x="388" y="{y}">{escape(_short(label, 22))}</text>')
        parts.append(f'<text class="legend-value" x="{WIDTH - 24}" y="{y}" text-anchor="end">{100 * v / total:.1f}%</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _extra_css(theme: str | None, export: bool) -> str:
    css = ""
    if theme in ("light", "dark"):
        css += f"  :root {{ color-scheme: {theme}; {LIGHT_VARS if theme == 'light' else DARK_VARS} }}\n"
    if export:
        css += EXPORT_CSS
    return css


def html_page(title: str, subtitle: str, svg: str, theme: str | None = None, export: bool = False) -> str:
    return Template(PAGE).substitute(
        title=escape(title), subtitle=escape(subtitle), svg=svg,
        light_vars=LIGHT_VARS, dark_vars=DARK_VARS, extra=_extra_css(theme, export),
    )


def safe_svg(svg: str) -> bool:
    """True only for markup built from the elements and attributes our charts use."""
    if len(svg) > MAX_SVG_CHARS or "<!DOCTYPE" in svg or "<!ENTITY" in svg:
        return False
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return False
    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str) or not tag.startswith(SVG_NS) or tag[len(SVG_NS):] not in SVG_TAGS:
            return False
        if any(name not in SVG_ATTRS for name in element.attrib):
            return False
    return root.tag == SVG_NS + "svg"


def parse_page(page: str) -> tuple[str, str, str] | None:
    """(title, subtitle, svg) from one of our chart pages, or None if it doesn't look like one."""
    h1, sub = _H1.search(page), _SUB.search(page)
    start, end = page.find("<svg"), page.rfind("</svg>")
    if not (h1 and sub) or start < 0 or end < start:
        return None
    return unescape(h1.group(1)), unescape(sub.group(1)), page[start : end + len("</svg>")]


def is_genuine_page(page: str) -> bool:
    """True if the page is exactly what our generator produces from its own parts."""
    parts = parse_page(page)
    return parts is not None and html_page(*parts) == page


def export_page(page: str, theme: str = "light") -> str:
    """A fresh, fixed-theme, fill-the-window page rebuilt from a chart's title, subtitle and svg."""
    if theme not in ("light", "dark"):
        raise ValueError("theme must be 'light' or 'dark'")
    parts = parse_page(page)
    if parts is None:
        raise ValueError("this does not look like a Jinni chart page")
    title, subtitle, svg = parts
    if not safe_svg(svg):
        raise ValueError("the chart contains elements the exporter does not allow")
    return html_page(title, subtitle, svg, theme=theme, export=True)


def export_svg(page: str, theme: str = "light") -> str:
    """Return a standalone, styled SVG from a genuine chart page."""
    if theme not in ("light", "dark"):
        raise ValueError("theme must be 'light' or 'dark'")
    parts = parse_page(page)
    if parts is None:
        raise ValueError("this does not look like a Jinni chart page")
    svg = parts[2]
    if not safe_svg(svg):
        raise ValueError("the chart contains elements the exporter does not allow")
    css = SVG_EXPORT_CSS.replace("$vars", LIGHT_VARS if theme == "light" else DARK_VARS)
    boundary = svg.find(">")
    return svg[:boundary + 1] + f"\n<style>{css}</style>\n" + svg[boundary + 1:]
