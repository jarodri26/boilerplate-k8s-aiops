from datetime import datetime, timezone


def _parse_timestamp(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def event_recency(ev: dict) -> datetime | None:
    """Recencia do evento: series.lastObservedTime -> eventTime -> deprecatedLastTimestamp."""
    series = ev.get("series") or {}
    for value in (
        series.get("lastObservedTime"),
        ev.get("eventTime"),
        ev.get("deprecatedLastTimestamp"),
    ):
        parsed = _parse_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def to_contract(ev: dict, recency: datetime) -> dict:
    """Converte um evento cru de events.k8s.io/v1 para o contrato de saida do coletor."""
    metadata = ev.get("metadata") or {}
    regarding = ev.get("regarding") or {}
    return {
        "uid": metadata.get("uid") or "",
        "type": ev.get("type") or "",
        "reason": ev.get("reason") or "",
        "message": ev.get("note") or "",
        "namespace": metadata.get("namespace") or "",
        "involved_object": {
            "kind": regarding.get("kind") or "",
            "name": regarding.get("name") or "",
            "namespace": regarding.get("namespace") or "",
        },
        "timestamp": recency.isoformat(),
    }
