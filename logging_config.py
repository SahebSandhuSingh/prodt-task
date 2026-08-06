import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict


# =============================================================================
# SECURITY & PRIVACY POLICY: ZERO GUEST PII LOGGING
# -----------------------------------------------------------------------------
# Under no circumstances should guest PII (guest_name, email, phone, payment details)
# be logged by any logger in this application. Only structural tracing IDs
# (request_id, workflow_id, booking_id, supplier_id, supplier_reservation_id)
# and operational status codes should be passed into extra context dicts.
# =============================================================================


class JSONFormatter(logging.Formatter):
    """
    Structured JSON log formatter for single-line parseable log output.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_object: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include tracing contextual fields if available
        for attr in ("request_id", "workflow_id", "booking_id", "supplier_id", "supplier_reservation_id", "error"):
            if hasattr(record, attr):
                val = getattr(record, attr)
                if val is not None:
                    log_object[attr] = str(val)

        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_object)


def setup_json_logging(level: int = logging.INFO) -> None:
    """
    Configure global logging to format records as structured JSON.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing default handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
