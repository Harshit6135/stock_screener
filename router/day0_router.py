import logging

from utils.logger import setup_logger
from services.day0_service import Day0Service


BASE_URL = "http://127.0.0.1:5000"
logger = setup_logger(name="Orchestrator")

def init_db():
    logger.info("Initializing Instruments List...")

    day0 = Day0Service()
    day0.run_day0_process()
