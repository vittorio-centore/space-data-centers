"""Intent validation: every tool is gated; planner overrides are rejected."""

from app.assistant.intents import (
    ValidatedAction,
    ValidationError,
    WorldCatalog,
    canonicalize_tool,
    validate_intent,
)

CATALOG = WorldCatalog(
    link_ids=frozenset(
        {
            "link-gs-ashburn-orbital-iss-cheap",
            "link-earth-us-east-gs-ashburn",
        }
    ),
    job_ids=frozenset({"job-abc123"}),
    station_ids=frozenset({"gs-ashburn", "gs-madrid"}),
    node_ids=frozenset({"earth-us-east", "orbital-iss-cheap"}),
)


def _ok(name, args=None) -> ValidatedAction:
    out = validate_intent(name, args or {}, CATALOG)
    assert isinstance(out, ValidatedAction), getattr(out, "message", out)
    return out


def _err(name, args=None) -> ValidationError:
    out = validate_intent(name, args or {}, CATALOG)
    assert isinstance(out, ValidationError), out
    return out


def test_canonicalize_aliases():
    assert canonicalize_tool("Pause") == "pause"
    assert canonicalize_tool("resume") == "play"
    assert canonicalize_tool("place_job") == "submit_job"
    assert canonicalize_tool("explode") is None


def test_unknown_tool_rejected():
    err = _err("replan", {})
    assert "unknown" in err.message


def test_play_pause_reject_extra_fields():
    assert _ok("play").args == {}
    assert _ok("pause").args == {}
    err = _err("play", {"speed": 99})
    assert "unexpected" in err.message


def test_submit_rejects_forced_node():
    for key in ("assigned_node_id", "compute_node_id", "force_node", "node_id"):
        err = _err("submit_job", {key: "orbital-iss-cheap"})
        assert "planner override" in err.message


def test_submit_defaults_and_station_check():
    act = _ok("submit_job", {})
    assert "assigned_node_id" not in act.args
    assert "compute_node_id" not in act.args
    assert act.args["source_id"] == "gs-ashburn"
    assert act.args["input_bytes"] == 5_000_000

    err = _err("submit_job", {"source_id": "gs-paris"})
    assert "unknown source_id" in err.message


def test_submit_bounds():
    assert "out of range" in _err("submit_job", {"input_bytes": 0}).message
    assert "out of range" in _err("submit_job", {"work": 2_000_000}).message
    assert "must be a number" in _err("submit_job", {"work": "lots"}).message


def test_submit_thesis_preset():
    act = _ok("submit_job", {"preset": "case_a_cheap_loses"})
    assert act.args == {"preset": "a"}
    err = _err("submit_job", {"preset": "migrate-to-iss"})
    assert "unknown preset" in err.message


def test_explain_unknown_job():
    err = _err("explain_plan", {"job_id": "job-missing"})
    assert "unknown job_id" in err.message
    act = _ok("explain_plan", {"job_id": "job-abc123"})
    assert act.args["job_id"] == "job-abc123"
    assert _ok("explain_plan", {}).args == {}


def test_disrupt_requires_known_link():
    err = _err("disrupt_link", {})
    assert "link_id is required" in err.message
    err = _err("disrupt_link", {"link_id": "link-fake"})
    assert "unknown link_id" in err.message
    act = _ok("disrupt_link", {"link_id": "link-gs-ashburn-orbital-iss-cheap", "action": "down"})
    assert act.args["action"] == "down"
    act = _ok("disrupt_link", {"link_id": "link-earth-us-east-gs-ashburn", "action": "restore"})
    assert act.args["action"] == "clear"


def test_disrupt_bandwidth_bounds():
    err = _err(
        "disrupt_link",
        {"link_id": "link-earth-us-east-gs-ashburn", "bandwidth_factor": 4},
    )
    assert "0–1" in err.message


def test_read_state_focus():
    assert _ok("read_state", {}).args["focus"] == "all"
    assert _ok("status", {"focus": "jobs"}).tool == "read_state"
    assert "focus" in _err("read_state", {"focus": "secrets"}).message


def test_empty_catalog_skips_id_membership():
    empty = WorldCatalog()
    out = validate_intent("disrupt_link", {"link_id": "anything"}, empty)
    assert isinstance(out, ValidatedAction)
