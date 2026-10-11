def test_log_filter_redacts_formatted_arguments_and_traceback():
    import io
    import logging

    from src.gates.security import RedactingLogFilter

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(RedactingLogFilter())
    logger = logging.getLogger("screener.phase1-verification")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info("job 42 stage provider api_secret=%s", "DO_NOT_PERSIST")
    try:
        raise RuntimeError("access_token=DO_NOT_PERSIST")
    except RuntimeError:
        logger.exception("job 42 failed")
    logger.removeHandler(handler)
    text = output.getvalue()
    assert "DO_NOT_PERSIST" not in text
    assert "job 42" in text
    assert "RuntimeError" in text
