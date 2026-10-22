import asyncio

import pytest

import retry
from retry import with_retries


@pytest.fixture
def sleeps(monkeypatch):
    waited = []

    async def fake_sleep(delay):
        waited.append(delay)

    monkeypatch.setattr(retry, "sleep", fake_sleep)
    return waited


class Flaky:
    def __init__(self, fails):
        self.fails = fails
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise ConnectionError("down")
        return "ok"


def test_succeeds_after_failures(sleeps):
    fn = Flaky(2)
    result = asyncio.run(with_retries(fn, 3, 1.0, (ConnectionError,)))
    assert result == "ok"
    assert fn.calls == 3
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_all_attempts(sleeps):
    fn = Flaky(10)
    with pytest.raises(ConnectionError):
        asyncio.run(with_retries(fn, 3, 1.0, (ConnectionError,)))
    assert fn.calls == 3


def test_does_not_retry_other_errors(sleeps):
    async def bug():
        raise ValueError("my bug")

    with pytest.raises(ValueError):
        asyncio.run(with_retries(bug, 3, 1.0, (ConnectionError,)))
    assert sleeps == []