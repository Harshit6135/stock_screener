
import os
import logging

from datetime import datetime

try:
    from pythonjsonlogger import jsonlogger
    HAS_JSON_LOGGER = True
except ImportError:
    HAS_JSON_LOGGER = False


def setup_logger(name="StockScreener", log_dir="logs"):
    """
    Set up a logger with JSON formatting for structured logging.
    
    Parameters:
        name (str): Logger name
        log_dir (str): Directory for log files
        
    Returns:
        logging.Logger: Configured logger instance
    """
    os.makedirs(log_dir, exist_ok=True)
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"stock_screener_{date_str}.log")
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # File Handler with JSON formatting
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setLevel(logging.INFO)
    
    if HAS_JSON_LOGGER:
        json_format = jsonlogger.JsonFormatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s',
            rename_fields={'asctime': 'timestamp', 'levelname': 'level'}
        )
        file_handler.setFormatter(json_format)
    else:
        file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        file_handler.setFormatter(file_format)
    
    # Console Handler (human-readable for debugging)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(levelname)s | %(name)s | %(message)s')
    console_handler.setFormatter(console_format)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

