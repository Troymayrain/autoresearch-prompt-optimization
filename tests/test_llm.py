import json

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


def test_call_optimizer_llm_rejects_unknown_provider_without_network():
    with pytest.raises(ValueError, match="unsupported optimizer provider"):
        call_optimizer_llm("local", "model", "system", "user")
