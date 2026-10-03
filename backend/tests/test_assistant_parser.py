from app.assistant.intents import WorldCatalog, validate_intent, ValidatedAction
from app.assistant.parser import parse_offline

CATALOG = WorldCatalog(
    link_ids=frozenset({"link-gs-ashburn-orbital-iss-cheap"}),
    job_ids=frozenset(),
    station_ids=frozenset({"gs-ashburn", "gs-madrid"}),
    node_ids=frozenset(),
)


def _validated(text):
    raw = parse_offline(text, CATALOG)
    assert raw
    out = validate_intent(raw[0]["tool"], raw[0].get("args"), CATALOG)
    assert isinstance(out, ValidatedAction), getattr(out, "message", out)
    return out


def test_offline_play_pause_submit_explain():
    assert _validated("please pause the simulation").tool == "pause"
    assert _validated("play").tool == "play"
    assert _validated("submit a job").tool == "submit_job"
    assert _validated("explain the plan").tool == "explain_plan"
    assert _validated("run thesis case a").args["preset"] == "a"


def test_offline_disrupt_resolves_known_link():
    act = _validated("disrupt the ISS Ashburn link")
    assert act.tool == "disrupt_link"
    assert act.args["link_id"] == "link-gs-ashburn-orbital-iss-cheap"
    assert act.args["action"] == "down"
