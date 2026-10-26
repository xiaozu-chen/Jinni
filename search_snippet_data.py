"""Extract bounded numeric candidates from web search snippets."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

MAX_POINTS = 50
MAX_SNIPPET_CHARS = 500
NUMBER = r"(?P<currency>USD\s*|[$€£¥])?\s*(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<scale>thousand|million|billion|trillion|[KMBT])?\s*(?P<percent>%)?"
PAIR_RE = re.compile(rf"(?:^|[,;|]\s*)(?P<label>[^,;|:]{{1,40}}?)\s*[:=]\s*{NUMBER}", re.IGNORECASE)
NUMBER_RE = re.compile(NUMBER, re.IGNORECASE)
SCALE = {
    "k": Decimal(1_000), "thousand": Decimal(1_000),
    "m": Decimal(1_000_000), "million": Decimal(1_000_000),
    "b": Decimal(1_000_000_000), "billion": Decimal(1_000_000_000),
    "t": Decimal(1_000_000_000_000), "trillion": Decimal(1_000_000_000_000),
}
CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


@dataclass(frozen=True)
class SearchPoint:
    label: str
    value: str
    unit: str
    source_title: str
    source_url: str
    snippet: str


def _number_value(match: re.Match[str]) -> tuple[str, str] | None:
    try:
        value = Decimal(match.group("number").replace(",", ""))
    except InvalidOperation:
        return None
    scale = (match.group("scale") or "").casefold()
    if scale:
        value *= SCALE[scale]
    currency = (match.group("currency") or "").strip()
    unit = CURRENCY.get(currency, currency.upper()) if currency else ("%" if match.group("percent") else "")
    return format(value, "f"), unit


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def extract_points(results: list[dict[str, Any]], query: str) -> list[SearchPoint]:
    points = []
    for result in results[:5]:
        title = " ".join(str(result.get("title") or "Search result").split())[:160]
        url = "".join(ch for ch in str(result.get("href") or result.get("url") or "") if ch.isprintable())[:2_000]
        snippet = " ".join(str(result.get("body") or result.get("snippet") or "").split())[:MAX_SNIPPET_CHARS]
        if not _valid_url(url) or not snippet:
            continue
        pairs = list(PAIR_RE.finditer(snippet))
        if pairs:
            for pair in pairs:
                label = " ".join(pair.group("label").strip(" .-—").split())[:80]
                parsed = _number_value(pair)
                if label and parsed:
                    points.append(SearchPoint(label, *parsed, title, url, snippet))
                    if len(points) >= MAX_POINTS:
                        return points
            continue

        values = []
        for match in NUMBER_RE.finditer(snippet):
            parsed = _number_value(match)
            if not parsed:
                continue
            value, unit = parsed
            numeric = Decimal(value)
            if not unit and not match.group("scale") and numeric == numeric.to_integral_value() and 1900 <= numeric <= 2100:
                continue
            values.append((value, unit))
        if len(values) == 1:
            value, unit = values[0]
            points.append(SearchPoint(title or query[:80], value, unit, title, url, snippet))
        if len(points) >= MAX_POINTS:
            return points
    return points


def points_csv(points: list[SearchPoint]) -> bytes:
    if not points:
        raise ValueError("search snippets contained no unambiguous numeric values")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("label", "value", "unit", "source_title", "source_url", "snippet"))

    def safe_text(value: str) -> str:
        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    for point in points[:MAX_POINTS]:
        writer.writerow((safe_text(point.label), point.value, point.unit, safe_text(point.source_title),
                         safe_text(point.source_url), safe_text(point.snippet)))
    return stream.getvalue().encode("utf-8")
