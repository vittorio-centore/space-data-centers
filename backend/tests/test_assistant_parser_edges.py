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


def test_smalltalk_is_empty():
    assert parse_offline("hello") == []
    assert parse_offline("thanks!") == []


def test_start_a_job_and_clock_verbs():
    assert _parse("start a job").tool == "submit_job"
    assert _parse("start the simulation").tool == "play"
    assert _parse("stop the clock").tool == "pause"


def test_job_deadline_and_compact_mb():
    act = _parse("submit a job with 8MB input deadline 2 hours")
    assert act.args["input_bytes"] == 8_000_000
    assert act.args["deadline_offset_s"] == 7200


def test_restore_iss_ashburn_without_link_word():
    act = _parse("restore iss ashburn")
    assert act.tool == "disrupt_link"
    assert act.args["action"] == "clear"
