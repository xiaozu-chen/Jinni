import logging
import sys

from runtime.log_safety import SecretScrubber, scrub_secrets


def test_scrubs_common_secret_shapes():
    message = "api_key=secret-value Authorization: Bearer abc.def token=ghp_12345678901234567890"

    scrubbed = scrub_secrets(message)

    assert "secret-value" not in scrubbed
    assert "abc.def" not in scrubbed
    assert "ghp_12345678901234567890" not in scrubbed
    assert scrubbed.count("[redacted]") >= 3


def test_log_filter_scrubs_message_arguments_and_traceback():
    try:
        raise ValueError("password='inside-error'")
    except ValueError:
        record = logging.LogRecord("jinni.test", logging.ERROR, __file__, 1, "token=%s", ("abc123",), sys.exc_info())

    SecretScrubber().filter(record)
    rendered = record.getMessage() + (record.exc_text or "")

    assert "abc123" not in rendered
    assert "inside-error" not in rendered
    assert "[redacted]" in rendered
