import json
import logging
from datetime import datetime

from app.core.logging import JsonFormatter


def test_json_log_line_has_a_real_timestamp_on_every_platform():
    # Regression: the formatter used time.strftime with "%f", which raises ValueError on Windows
    # (and printed a literal "%f" on Linux), so every log line failed to print.
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "hello world" and line["level"] == "INFO"
    assert "%f" not in line["timestamp"]
    parsed = datetime.fromisoformat(line["timestamp"])  # e.g. 2026-10-09T10:31:48.123+00:00
    assert parsed.tzinfo is not None and abs(parsed.timestamp() - record.created) < 0.002
