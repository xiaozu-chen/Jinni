import logging
import re

SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|authorization)\b\s*[:=]\s*)(?:Bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
SECRET_QUERY = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|key)=)[^&#\s]+"
)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
KNOWN_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|AKIA[A-Z0-9]{16})\b")


def scrub_secrets(message: str) -> str:
    message = SECRET_ASSIGNMENT.sub(r"\1[redacted]", message)
    message = SECRET_QUERY.sub(r"\1[redacted]", message)
    message = BEARER.sub("Bearer [redacted]", message)
    return KNOWN_TOKEN.sub("[redacted]", message)


class SecretScrubber(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub_secrets(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = scrub_secrets(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = scrub_secrets(record.stack_info)
        return True
