from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from optimizer.dataset import TaskName


@dataclass(frozen=True)
class OptimizerProposal:
    hypothesis: str
    expected_effect: str
    risk: str
    target_failures: list[str]
    prompt_file: str


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optimizer_timeout() -> float | None:
    value = _optional_env("OPTIMIZER_TIMEOUT_SECONDS")
    return None if value is None else float(value)


def _client_kwargs(api_key_name: str, base_url_name: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"api_key": os.getenv(api_key_name)}
    base_url = _optional_env(base_url_name)
    timeout = _optimizer_timeout()
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs


def _mutation_boundary(task: TaskName) -> dict[str, list[str]]:
    if task == "code":
        return {
            "allowed": [
                "code extraction",
                "number output",
                "code-candidate detection",
            ],
            "forbidden": [
                "type classification",
                "brand",
                "cardType",
                "country",
                "currency",
                "denomination",
            ],
        }
    if task == "type":
        return {
            "allowed": [
                "physical-versus-electronic type rules in PROMPT_COMPLEX and PROMPT_COMPLET",
            ],
            "forbidden": [
                "PROMPT_DETECT",
                "code extraction",
                "number output",
                "output format",
                "brand",
                "cardType",
                "country",
                "currency",
                "denomination",
            ],
        }
    raise ValueError(f"unsupported task: {task}")


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise
        data = json.loads(cleaned[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("optimizer response must be a JSON object")
    return data


def parse_optimizer_response(text: str) -> OptimizerProposal:
    data = _json_object(text)
    required = ("hypothesis", "expected_effect", "risk", "prompt_file")
    missing = [
        key for key in required if not isinstance(data.get(key), str) or not data[key].strip()
    ]
    if missing:
        raise ValueError(f"optimizer response missing: {', '.join(missing)}")
    target_failures = data.get("target_failures")
    if not isinstance(target_failures, list) or not target_failures:
        raise ValueError("optimizer response target_failures must be a non-empty list")
    normalized_target_failures: list[str] = []
    for item in target_failures:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, int) and not isinstance(item, bool):
            value = str(item)
        else:
            raise ValueError(
                "optimizer response target_failures must contain strings or row numbers"
            )
        if not value:
            raise ValueError(
                "optimizer response target_failures must contain strings or row numbers"
            )
        normalized_target_failures.append(value)

    return OptimizerProposal(
        hypothesis=data["hypothesis"].strip(),
        expected_effect=data["expected_effect"].strip(),
        risk=data["risk"].strip(),
        target_failures=normalized_target_failures,
        prompt_file=data["prompt_file"],
    )


def build_optimizer_messages(
    current_prompt: str,
    summary: dict[str, Any],
    failure_clusters: dict[str, Any],
    failures: list[dict[str, Any]],
    recent_diffs: list[str],
    task: TaskName = "code",
) -> tuple[str, str]:
    boundary = _mutation_boundary(task)
    system = (
        "You improve a gift card OCR prompt. Return JSON only with exactly "
        "hypothesis, expected_effect, risk, target_failures, and prompt_file. "
        "target_failures must be a non-empty JSON array of row numbers or "
        "failure categories from the provided evidence. Only the prompt file may "
        "change; do not change scoring, runtime code, datasets, or post-processing. "
        f"Selected task: {task}. Allowed changes: {', '.join(boundary['allowed'])}. "
        f"Forbidden changes: {', '.join(boundary['forbidden'])}. "
        "prompt_file must be the complete JavaScript file content starting with module.exports. "
        "Do not return a diff, patch, markdown, or abbreviated excerpt."
    )
    user = json.dumps(
        {
            "task": task,
            "mutation_boundary": boundary,
            "current_prompt": current_prompt,
            "summary": summary,
            "failure_clusters": failure_clusters,
            "representative_failures": failures[:30],
            "target_failure_guidance": (
                "Set target_failures to row numbers or failure_category values from "
                "representative_failures and failure_clusters."
            ),
            "recent_diffs": recent_diffs[-5:],
        },
        ensure_ascii=False,
        indent=2,
    )
    return system, user


def call_optimizer_llm(provider: str, model: str, system: str, user: str) -> OptimizerProposal:
    normalized = provider.strip().lower()
    if normalized == "gemini":
        from google import genai

        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
            ),
        )
        return parse_optimizer_response(response.text or "")

    if normalized == "openai":
        from openai import OpenAI

        response = OpenAI(**_client_kwargs("OPENAI_API_KEY", "OPENAI_BASE_URL")).chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return parse_optimizer_response(response.choices[0].message.content or "")

    if normalized == "anthropic":
        import anthropic

        response = anthropic.Anthropic(
            **_client_kwargs("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")
        ).messages.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text if response.content else ""
        return parse_optimizer_response(text)

    raise ValueError(f"unsupported optimizer provider: {provider}")
