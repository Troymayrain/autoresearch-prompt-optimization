import json
import sys
import types

import pytest

from optimizer.llm import OptimizerProposal, build_optimizer_messages, call_optimizer_llm, parse_optimizer_response


def test_parse_optimizer_response_extracts_json_object():
    text = '```json\n{"hypothesis":"h","expected_effect":"e","risk":"r","prompt_file":"module.exports={}"}\n```'

    proposal = parse_optimizer_response(text)

    assert proposal == OptimizerProposal("h", "e", "r", "module.exports={}")


def test_parse_optimizer_response_rejects_missing_prompt():
    with pytest.raises(ValueError, match="prompt_file"):
        parse_optimizer_response('{"hypothesis":"h","expected_effect":"e","risk":"r"}')


def test_parse_optimizer_response_trims_fields_and_ignores_metadata():
    proposal = parse_optimizer_response(
        '{"hypothesis":" h ","expected_effect":" e ","risk":" r ","prompt_file":" p\\n","notes":"drop"}'
    )

    assert proposal == OptimizerProposal("h", "e", "r", " p\n")


def test_parse_optimizer_response_extracts_prefixed_suffixed_json_object():
    proposal = parse_optimizer_response(
        'prefix {"hypothesis":"h","expected_effect":"e","risk":"r","prompt_file":"p"} suffix'
    )

    assert proposal == OptimizerProposal("h", "e", "r", "p")


def test_parse_optimizer_response_rejects_text_without_json_object():
    with pytest.raises(json.JSONDecodeError):
        parse_optimizer_response("no json here")


def test_parse_optimizer_response_rejects_malformed_json_object():
    with pytest.raises(json.JSONDecodeError):
        parse_optimizer_response('prefix {"hypothesis": "h",} suffix')


def test_parse_optimizer_response_rejects_non_string_fields():
    with pytest.raises(ValueError, match="risk"):
        parse_optimizer_response(
            '{"hypothesis":"h","expected_effect":"e","risk":1,"prompt_file":"module.exports={}"}'
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


def test_call_optimizer_llm_rejects_unknown_provider_without_network():
    with pytest.raises(ValueError, match="unsupported optimizer provider"):
        call_optimizer_llm("local", "model", "system", "user")


def _proposal_json() -> str:
    return json.dumps(
        {
            "hypothesis": "h",
            "expected_effect": "e",
            "risk": "r",
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

    assert proposal == OptimizerProposal("h", "e", "r", "p")


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

    assert proposal == OptimizerProposal("h", "e", "r", "p")


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

    assert proposal == OptimizerProposal("h", "e", "r", "p")
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

    assert proposal == OptimizerProposal("h", "e", "r", "p")


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

    assert proposal == OptimizerProposal("h", "e", "r", "p")
    assert captured == {
        "api_key": "relay-key",
        "base_url": "https://relay.example.com",
        "timeout": 123.5,
    }
