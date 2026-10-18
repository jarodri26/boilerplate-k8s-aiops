import logging
import math
import os

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_INTERVAL_MINUTES = 3


def get_collection_interval_seconds() -> float:
    raw = os.environ.get("EVENT_COLLECTION_INTERVAL_MINUTES")
    if raw is None or raw.strip() == "":
        return DEFAULT_COLLECTION_INTERVAL_MINUTES * 60

    try:
        minutes = float(raw)
    except ValueError:
        minutes = None

    if minutes is None or not math.isfinite(minutes) or minutes <= 0:
        logger.warning(
            "EVENT_COLLECTION_INTERVAL_MINUTES invalido (%r); usando o padrao de %d minutos",
            raw,
            DEFAULT_COLLECTION_INTERVAL_MINUTES,
        )
        return DEFAULT_COLLECTION_INTERVAL_MINUTES * 60

    return minutes * 60
