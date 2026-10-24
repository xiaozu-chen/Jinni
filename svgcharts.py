import math
from html import escape
from string import Template

WIDTH, HEIGHT = 640, 360
LEFT, RIGHT, TOP, BOTTOM = 76, 24, 24, 72

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
  :root { --bg:#ffffff; --fg:#1f2328; --muted:#6b7280; --grid:#e5e7eb; --accent:#2563eb; color-scheme: light dark; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111418; --fg:#e6e8eb; --muted:#9aa4b2; --grid:#2a2f37; --accent:#60a5fa; }
  }
  body { margin:0; padding:24px; background:var(--bg); color:var(--fg); font-family: system-ui, "Segoe UI", sans-serif; }
  main { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 1.25rem; font-weight: 600; margin: 0 0 4px; }
  p.sub { color: var(--muted); margin: 0 0 16px; font-size: .9rem; }
  svg { width: 100%; height: auto; }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .axis { stroke: var(--muted); stroke-width: 1; }
  .tick, .xlabel, .axis-title { fill: var(--muted); font-size: 12px; }
  .value { fill: var(--fg); font-size: 11px; }
  .bar, .dot { fill: var(--accent); }
  .line { fill: none; stroke: var(--accent); stroke-width: 2.5; stroke-linejoin: round; }
</style>
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
    sign = "-" if value < 0 else ""
    v = abs(value)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= limit:
            text = f"{v / limit:.2f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return fmt(value)


def _svg(kind: str, labels: list[str], values: list[float], title: str, x_title: str, y_title: str) -> str:
    if not values or len(labels) != len(values):
        raise ValueError("labels and values must be the same non-zero length")

    n = len(values)
    plot_w = WIDTH - LEFT - RIGHT
    plot_h = HEIGHT - TOP - BOTTOM
    if kind == "bar":
        low, high = min(0.0, min(values)), max(0.0, max(values))
    else:
        low, high = min(values), max(values)
    ticks = nice_ticks(low, high)
    lo, hi = ticks[0], ticks[-1]

    def y_of(v: float) -> float:
        return TOP + plot_h - (v - lo) / (hi - lo) * plot_h

    slot = plot_w / n
    centers = [LEFT + (i + 0.5) * slot for i in range(n)]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(title)}">',
        f"<title>{escape(title)}</title>",
    ]
    for t in ticks:
        y = y_of(t)
        parts.append(f'<line class="grid" x1="{LEFT}" y1="{y:.1f}" x2="{WIDTH - RIGHT}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{compact(t)}</text>')
    parts.append(f'<line class="axis" x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{TOP + plot_h}"/>')
    zero_y = y_of(0) if lo <= 0 <= hi else TOP + plot_h
    parts.append(f'<line class="axis" x1="{LEFT}" y1="{zero_y:.1f}" x2="{WIDTH - RIGHT}" y2="{zero_y:.1f}"/>')

    if kind == "bar":
        bar_w = slot * 0.7
        for c, label, v in zip(centers, labels, values):
            top, bottom = sorted((y_of(v), y_of(0)))
            parts.append(
                f'<rect class="bar" x="{c - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{bottom - top:.1f}">'
                f"<title>{escape(label)}: {fmt(v)}</title></rect>"
            )
    else:
        points = " ".join(f"{c:.1f},{y_of(v):.1f}" for c, v in zip(centers, values))
        parts.append(f'<polyline class="line" points="{points}"/>')
        for c, label, v in zip(centers, labels, values):
            parts.append(
                f'<circle class="dot" cx="{c:.1f}" cy="{y_of(v):.1f}" r="3.5">'
                f"<title>{escape(label)}: {fmt(v)}</title></circle>"
            )

    if n <= 12:
        for c, v in zip(centers, values):
            y = y_of(v) - 6 if v >= 0 else y_of(v) + 14
            parts.append(f'<text class="value" x="{c:.1f}" y="{y:.1f}" text-anchor="middle">{fmt(v)}</text>')

    rotate = n > 8
    limit = 10 if rotate else 14
    label_y = TOP + plot_h + 18
    for c, label in zip(centers, labels):
        short = label if len(label) <= limit else label[: limit - 1] + "…"
        if rotate:
            parts.append(
                f'<text class="xlabel" x="{c:.1f}" y="{label_y}" text-anchor="end" '
                f'transform="rotate(-40 {c:.1f} {label_y})">{escape(short)}</text>'
            )
        else:
            parts.append(f'<text class="xlabel" x="{c:.1f}" y="{label_y}" text-anchor="middle">{escape(short)}</text>')

    mid = TOP + plot_h / 2
    parts.append(f'<text class="axis-title" x="{LEFT + plot_w / 2:.1f}" y="{HEIGHT - 8}" text-anchor="middle">{escape(x_title)}</text>')
    parts.append(f'<text class="axis-title" x="14" y="{mid:.1f}" text-anchor="middle" transform="rotate(-90 14 {mid:.1f})">{escape(y_title)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def bar_chart(labels: list[str], values: list[float], title: str, x_title: str, y_title: str) -> str:
    return _svg("bar", labels, values, title, x_title, y_title)


def line_chart(labels: list[str], values: list[float], title: str, x_title: str, y_title: str) -> str:
    return _svg("line", labels, values, title, x_title, y_title)


def html_page(title: str, subtitle: str, svg: str) -> str:
    return Template(PAGE).substitute(title=escape(title), subtitle=escape(subtitle), svg=svg)