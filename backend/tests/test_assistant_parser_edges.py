"""Offline parser coverage beyond the happy-path phrases."""

from app.assistant.intents import WorldCatalog, validate_intent, ValidatedAction
from app.assistant.parser import parse_offline

CATALOG = WorldCatalog(
    link_ids=frozenset(
        {
            "link-gs-ashburn-orbital-iss-cheap",
            "link-earth-us-east-gs-ashburn",
        }
    ),
    job_ids=frozenset({"job-00000003"}),
    station_ids=frozenset({"gs-ashburn", "gs-madrid"}),
    node_ids=frozenset(),
)


def _parse(text):
    raw = parse_offline(text, CATALOG)
    assert raw
    out = validate_intent(raw[0]["tool"], raw[0].get("args"), CATALOG)
    assert isinstance(out, ValidatedAction), getattr(out, "message", out)
    return out


def test_empty_text_no_tools():
    assert parse_offline("", CATALOG) == []
    assert parse_offline("   ", CATALOG) == []


def test_status_and_mb_job():
    assert _parse("what's happening").tool == "read_state"
    act = _parse("submit a job with 8 mb input from madrid source")
    assert act.tool == "submit_job"
    assert act.args.get("input_bytes") == 8_000_000
    assert act.args.get("source_id") == "gs-madrid"


def test_restore_link_phrase():
    act = _parse("restore the ISS Ashburn link")
    assert act.tool == "disrupt_link"
    assert act.args["action"] == "clear"


def test_explain_with_job_id():
    act = _parse("explain plan for job-00000003")
    assert act.tool == "explain_plan"
    assert act.args["job_id"] == "job-00000003"


def test_unknown_falls_back_to_read_state():
    act = _parse("hello there constellation")
    assert act.tool == "read_state"
