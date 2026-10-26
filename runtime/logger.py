import logging
from logging.handlers import RotatingFileHandler

from settings.config import settings
from runtime.log_safety import SecretScrubber

def setup_logging() -> None:
    logger = logging.getLogger("jinni")
    if logger.handlers:
        return
    logger.setLevel(logging.DEBUG)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_file, maxBytes=500_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    handler.addFilter(SecretScrubber())
    logger.addHandler(handler)
    logger.propagate = False
