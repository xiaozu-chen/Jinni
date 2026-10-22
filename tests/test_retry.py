import pytest

import retry
from retry import with_retries


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(retry.time, "sleep", waited.append)
    return waited


class Flaky:
    def __init__(self, fails):
        self.fails = fails
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise ConnectionError("down")
        return "ok"


def test_succeeds_after_failures(sleeps):
    fn = Flaky(2)
    assert with_retries(fn, 3, 1.0, (ConnectionError,)) == "ok"
    assert fn.calls == 3
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_all_attempts(sleeps):
    fn = Flaky(10)
    with pytest.raises(ConnectionError):
        with_retries(fn, 3, 1.0, (ConnectionError,))
    assert fn.calls == 3


def test_does_not_retry_other_errors(sleeps):
    def bug():
        raise ValueError("my bug")

    with pytest.raises(ValueError):
        with_retries(bug, 3, 1.0, (ConnectionError,))
    assert sleeps == []