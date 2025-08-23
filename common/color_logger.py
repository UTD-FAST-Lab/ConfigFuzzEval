import logging
import sys

# Add SUCCESS level to logging module
logging.SUCCESS = 25  # Between INFO (20) and WARNING (30)
logging.addLevelName(logging.SUCCESS, "SUCCESS")

COLOR_CODES = {
    "DEBUG": "\033[36m",    # Cyan
    "INFO": "\033[34m",     # Blue
    "SUCCESS": "\033[32m",  # Green
    "WARNING": "\033[33m",  # Yellow
    "ERROR": "\033[31m",    # Red
    "CRITICAL": "\033[41m", # Red background
}
RESET_CODE = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        levelname = record.levelname
        if levelname in COLOR_CODES:
            record.levelname = f"{COLOR_CODES[levelname]}[{levelname}]{RESET_CODE}"
        else:
            record.levelname = f"[{levelname}]"
        return super().format(record)


def get_logger(name=None, level=logging.INFO):
    """
    Returns a logger with colorized output.
    :param name: Logger name (None = root logger)
    :param level: Logging level
    """
    logger = logging.getLogger(name)
    if not logger.handlers:  # Avoid duplicate handlers
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColorFormatter("%(levelname)s - %(message)s"))
        logger.addHandler(handler)
    
    # Add success method to logger
    def success(self, message, *args, **kwargs):
        if self.isEnabledFor(logging.SUCCESS):
            self._log(logging.SUCCESS, message, args, **kwargs)
    
    # Bind the success method to the logger instance
    logger.success = success.__get__(logger, type(logger))
    
    logger.setLevel(level)
    return logger
