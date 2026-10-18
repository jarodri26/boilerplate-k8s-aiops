import json

from my_agent_app.collector.handler import EventHandler


async def test_handler_imprime_eventos_no_stdout(capsys):
    events = [
        {"uid": "u1", "reason": "BackOff"},
        {"uid": "u2", "reason": "FailedScheduling"},
    ]
    await EventHandler().handle(events)

    out = capsys.readouterr().out.splitlines()
    assert "2 evento(s)" in out[0]
    assert [json.loads(line) for line in out[1:]] == events
