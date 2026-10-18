import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from my_agent_app.collector.transform import event_recency, to_contract

logger = logging.getLogger(__name__)

# Recuo da janela para absorver publicacao tardia de eventos e skew de relogio app x cluster
MARGIN = timedelta(seconds=60)


@dataclass
class Selection:
    events: list[dict]
    recencies: dict[str, datetime]


class CollectionWindow:
    """Marca d'agua com margem + registro em memoria uid -> ultima recencia entregue."""

    def __init__(self, start: datetime, interval: timedelta, margin: timedelta = MARGIN):
        self.watermark = start - interval
        self.margin = margin
        self.sent: dict[str, datetime] = {}

    @property
    def lower_bound(self) -> datetime:
        return self.watermark - self.margin

    def select(self, raw_events: list[dict]) -> Selection:
        """Filtra eventos crus pela janela e pelo registro de uids. Nao altera o estado."""
        lower = self.lower_bound
        events: list[dict] = []
        recencies: dict[str, datetime] = {}
        for ev in raw_events:
            recency = event_recency(ev)
            if recency is None:
                logger.warning(
                    "Evento descartado sem series.lastObservedTime, eventTime ou deprecatedLastTimestamp: uid=%s",
                    (ev.get("metadata") or {}).get("uid"),
                )
                continue
            if recency <= lower:
                continue
            contract = to_contract(ev, recency)
            uid = contract["uid"]
            last_sent = self.sent.get(uid)
            if last_sent is not None and last_sent >= recency:
                continue
            events.append(contract)
            recencies[uid] = recency
        return Selection(events=events, recencies=recencies)

    def commit(self, collection_start: datetime, selection: Selection) -> None:
        """Registra a coleta bem-sucedida: avanca a marca d'agua e poda o registro."""
        self.sent.update(selection.recencies)
        self.watermark = collection_start
        lower = self.lower_bound
        self.sent = {uid: r for uid, r in self.sent.items() if r > lower}
