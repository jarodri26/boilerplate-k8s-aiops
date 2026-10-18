import json


class EventHandler:
    """Tratamento dos eventos coletados. Placeholder: o processamento real e o PRD 002."""

    async def handle(self, events: list[dict]) -> None:
        print(f"[EventHandler] {len(events)} evento(s) Warning recebido(s):")
        for event in events:
            print(json.dumps(event, ensure_ascii=False))
