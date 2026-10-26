import logging
import sys
from logging.handlers import RotatingFileHandler

from settings.config import settings
from runtime.log_safety import SecretScrubber

def setup_logging(*, console: bool = False) -> None:
    logger = logging.getLogger("jinni")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    if not any(isinstance(item, RotatingFileHandler) for item in logger.handlers):
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            settings.log_file, maxBytes=500_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        handler.addFilter(SecretScrubber())
        logger.addHandler(handler)
    if console and not any(getattr(item, "_jinni_console", False) for item in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        handler.addFilter(SecretScrubber())
        handler._jinni_console = True
        logger.addHandler(handler)
    logger.propagate = False
