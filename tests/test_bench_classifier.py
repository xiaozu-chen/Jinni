from collections import Counter

from bench_classifier import PROMPTS
from thinking_classifier import parse_thinking_label


def test_classifier_benchmark_has_30_balanced_cases():
    assert len(PROMPTS) == 30
    assert Counter(expected for expected, _prompt in PROMPTS) == {"on": 15, "off": 15}


def test_classifier_only_accepts_exact_on_off_labels():
    assert parse_thinking_label("on") is True
    assert parse_thinking_label(" OFF ") is False
    assert parse_thinking_label("probably on") is None
    assert parse_thinking_label(None) is None
