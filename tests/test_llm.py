import json
import sys
import types

import pytest

from optimizer.llm import OptimizerProposal, build_optimizer_messages, call_optimizer_llm, parse_optimizer_response


def test_parse_optimizer_response_extracts_json_object():
    text = (
        '```json\n{"hypothesis":"h","expected_effect":"e","risk":"r",'
        '"target_failures":["row 2"],"prompt_file":"module.exports={}"}\n```'
    )

    proposal = parse_optimizer_response(text)

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], "module.exports={}")


def test_parse_optimizer_response_accepts_numeric_row_numbers():
    proposal = parse_optimizer_response(
        '{"hypothesis":"h","expected_effect":"e","risk":"r","target_failures":[3],'
        '"prompt_file":"module.exports={}"}'
    )

    assert proposal == OptimizerProposal("h", "e", "r", ["3"], "module.exports={}")


def test_parse_optimizer_response_rejects_missing_prompt():
    with pytest.raises(ValueError, match="prompt_file"):
        parse_optimizer_response('{"hypothesis":"h","expected_effect":"e","risk":"r","target_failures":["row 2"]}')


def test_parse_optimizer_response_rejects_missing_target_failures():
    with pytest.raises(ValueError, match="target_failures"):
        parse_optimizer_response('{"hypothesis":"h","expected_effect":"e","risk":"r","prompt_file":"p"}')


def test_parse_optimizer_response_rejects_empty_target_failures():
    with pytest.raises(ValueError, match="target_failures"):
        parse_optimizer_response(
            '{"hypothesis":"h","expected_effect":"e","risk":"r","target_failures":[],"prompt_file":"p"}'
        )


def test_parse_optimizer_response_rejects_invalid_target_failures():
    with pytest.raises(ValueError, match="target_failures"):
        parse_optimizer_response(
            '{"hypothesis":"h","expected_effect":"e","risk":"r","target_failures":["row 2",{"row":3}],'
            '"prompt_file":"p"}'
        )


def test_parse_optimizer_response_trims_fields_and_ignores_metadata():
    proposal = parse_optimizer_response(
        '{"hypothesis":" h ","expected_effect":" e ","risk":" r ","target_failures":[" row 2 "],'
        '"prompt_file":" p\\n","notes":"drop"}'
    )

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], " p\n")


def test_parse_optimizer_response_extracts_prefixed_suffixed_json_object():
    proposal = parse_optimizer_response(
        'prefix {"hypothesis":"h","expected_effect":"e","risk":"r",'
        '"target_failures":["wrong_code"],"prompt_file":"p"} suffix'
    )

    assert proposal == OptimizerProposal("h", "e", "r", ["wrong_code"], "p")


def test_parse_optimizer_response_rejects_text_without_json_object():
    with pytest.raises(json.JSONDecodeError):
        parse_optimizer_response("no json here")


def test_parse_optimizer_response_rejects_malformed_json_object():
    with pytest.raises(json.JSONDecodeError):
        parse_optimizer_response('prefix {"hypothesis": "h",} suffix')


def test_parse_optimizer_response_rejects_non_string_fields():
    with pytest.raises(ValueError, match="risk"):
        parse_optimizer_response(
            '{"hypothesis":"h","expected_effect":"e","risk":1,'
            '"target_failures":["row 2"],"prompt_file":"module.exports={}"}'
        )


def test_build_optimizer_messages_limits_unbounded_inputs():
    system, user = build_optimizer_messages(
        "prompt",
        {"business_accuracy": 90},
        {"wrong_code": 40},
        [{"id": index} for index in range(35)],
        [f"diff-{index}" for index in range(8)],
    )

    data = json.loads(user)
    assert "JSON only" in system
    assert "only" in system and "prompt file" in system
    assert data["current_prompt"] == "prompt"
    assert len(data["representative_failures"]) == 30
    assert data["representative_failures"][0] == {"id": 0}
    assert data["recent_diffs"] == ["diff-3", "diff-4", "diff-5", "diff-6", "diff-7"]


def test_build_optimizer_messages_includes_code_boundary():
    system, user = build_optimizer_messages("prompt", {}, {}, [], [], task="code")

    data = json.loads(user)
    assert data["task"] == "code"
    assert "code extraction" in system
    assert "number output" in system
    assert "type classification" in system
    assert "brand" in data["mutation_boundary"]["forbidden"]
    assert "cardType" in data["mutation_boundary"]["forbidden"]


def test_build_optimizer_messages_includes_type_boundary():
    system, user = build_optimizer_messages("prompt", {}, {}, [], [], task="type")

    data = json.loads(user)
    assert data["task"] == "type"
    assert "physical-versus-electronic type rules" in system
    assert "PROMPT_COMPLEX" in system
    assert "PROMPT_COMPLET" in system
    assert "PROMPT_DETECT" in data["mutation_boundary"]["forbidden"]
    assert "number output" in data["mutation_boundary"]["forbidden"]


def test_build_optimizer_messages_requests_target_failure_evidence():
    system, user = build_optimizer_messages(
        "prompt",
        {},
        {"wrong_code": 2},
        [{"row_number": 7, "failure_category": "wrong_code"}],
        [],
    )

    data = json.loads(user)
    assert "target_failures" in system
    assert "row" in data["target_failure_guidance"]
    assert "failure_category" in data["target_failure_guidance"]


def test_build_optimizer_messages_uses_focused_group_as_only_active_target_source():
    feedback_failures = {
        "task": "code",
        "feedback_set": "dev",
        "primary_groups": [
            {
                "key": "wrong_code_ocr_confusion",
                "rows": [7],
                "examples": [{"row_number": 7, "failure_category": "wrong_code"}],
            },
            {
                "key": "no_card_false_negative",
                "rows": [9],
                "examples": [{"row_number": 9, "failure_category": "no_card"}],
            },
        ],
        "secondary_groups": [{"key": "extra_code_output", "rows": [8], "examples": []}],
    }
    focused_group = feedback_failures["primary_groups"][0]

    system, user = build_optimizer_messages(
        "prompt",
        {"business_accuracy": 90.0},
        {"wrong_code": 2, "extra_code": 9},
        [{"row_number": 99, "failure_category": "wrong_code"}],
        [],
        feedback_failures=feedback_failures,
        focused_feedback_group=focused_group,
    )

    data = json.loads(user)
    assert "Dev Evaluation Set" in system
    assert data["focused_feedback_group"] == focused_group
    assert data["optimizer_feedback_set"] == {"task": "code", "feedback_set": "dev"}
    assert data["optimizer_background_evidence"]["inactive_primary_groups"] == [
        feedback_failures["primary_groups"][1]
    ]
    assert data["optimizer_background_evidence"]["secondary_groups"] == [
        {"key": "extra_code_output", "rows": [8], "examples": []}
    ]
    assert data["optimizer_background_evidence"]["failure_clusters"] == {
        "wrong_code": 2,
        "extra_code": 9,
    }
    assert "representative_failures" not in data
    assert "row 99" not in json.dumps(data)
    assert "focused_feedback_group" in data["target_failure_guidance"]
    assert "inactive" in data["target_failure_guidance"]


def test_build_optimizer_messages_includes_failed_strategy_memory_as_prohibition():
    failed_strategy_memory = [
        {
            "focused_group": "wrong_code_ocr_confusion",
            "strategy_summary": "tighten B/8 reading",
            "outcome": "unchanged",
            "target_rows": [7],
        }
    ]

    system, user = build_optimizer_messages(
        "prompt",
        {},
        {},
        [],
        [],
        feedback_failures={
            "task": "code",
            "feedback_set": "dev",
            "primary_groups": [],
            "secondary_groups": [],
        },
        focused_feedback_group={"key": "wrong_code_ocr_confusion", "rows": [7]},
        failed_strategy_memory=failed_strategy_memory,
    )

    data = json.loads(user)
    assert data["failed_strategy_memory"] == failed_strategy_memory
    assert "Do not repeat failed_strategy_memory" in system
    assert "do not repeat" in data["target_failure_guidance"]


def test_build_optimizer_messages_prioritizes_candidate_delta_over_recent_diffs():
    system, user = build_optimizer_messages(
        "prompt",
        {},
        {},
        [],
        ["diff-old"],
        candidate_delta_summaries=[
            {
                "primary_metric": {"name": "business_code_match", "delta": 0},
                "strict_only_changed_rows": [{"row_number": 7}],
                "infra_failure_rows": [{"row_number": 9}],
            }
        ],
    )

    data = json.loads(user)
    assert "Candidate Evaluation Delta" in system
    assert data["candidate_evaluation_delta_summary"] == [
        {
            "primary_metric": {"name": "business_code_match", "delta": 0},
            "strict_only_changed_rows": [{"row_number": 7}],
            "infra_failure_rows": [{"row_number": 9}],
        }
    ]
    assert data["recent_diffs"] == ["diff-old"]
    assert "recent_diffs are auxiliary" in data["feedback_priority"]
    assert "strict-only" in data["feedback_priority"]
    assert "infrastructure" in data["feedback_priority"]


def test_call_optimizer_llm_rejects_unknown_provider_without_network():
    with pytest.raises(ValueError, match="unsupported optimizer provider"):
        call_optimizer_llm("local", "model", "system", "user")


def _proposal_json() -> str:
    return json.dumps(
        {
            "hypothesis": "h",
            "expected_effect": "e",
            "risk": "r",
            "target_failures": ["row 2"],
            "prompt_file": "p",
        }
    )


def test_call_optimizer_llm_gemini_parses_response_without_network(monkeypatch):
    class FakeModels:
        def generate_content(self, **kwargs):
            return types.SimpleNamespace(text=_proposal_json())

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    fake_genai = types.SimpleNamespace(
        Client=FakeClient,
        types=types.SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs),
    )
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    proposal = call_optimizer_llm("gemini", "model", "system", "user")

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], "p")


def test_call_optimizer_llm_openai_parses_response_without_network(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            message = types.SimpleNamespace(content=_proposal_json())
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    proposal = call_optimizer_llm("openai", "model", "system", "user")

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], "p")


def test_call_optimizer_llm_openai_uses_relay_base_url_and_timeout(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            message = types.SimpleNamespace(content=_proposal_json())
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.example.com/v1")
    monkeypatch.setenv("OPTIMIZER_TIMEOUT_SECONDS", "123.5")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    proposal = call_optimizer_llm("openai", "model", "system", "user")

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], "p")
    assert captured == {
        "api_key": "relay-key",
        "base_url": "https://relay.example.com/v1",
        "timeout": 123.5,
    }


def test_call_optimizer_llm_anthropic_parses_response_without_network(monkeypatch):
    class FakeMessages:
        def create(self, **kwargs):
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=_proposal_json())])

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))

    proposal = call_optimizer_llm("anthropic", "model", "system", "user")

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], "p")


def test_call_optimizer_llm_anthropic_uses_relay_base_url_and_timeout(monkeypatch):
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=_proposal_json())])

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "relay-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://relay.example.com")
    monkeypatch.setenv("OPTIMIZER_TIMEOUT_SECONDS", "123.5")
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))

    proposal = call_optimizer_llm("anthropic", "model", "system", "user")

    assert proposal == OptimizerProposal("h", "e", "r", ["row 2"], "p")
    assert captured == {
        "api_key": "relay-key",
        "base_url": "https://relay.example.com",
        "timeout": 123.5,
    }
