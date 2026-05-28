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
    prompt_file: str


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

    return OptimizerProposal(
        hypothesis=data["hypothesis"].strip(),
        expected_effect=data["expected_effect"].strip(),
        risk=data["risk"].strip(),
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
        "hypothesis, expected_effect, risk, and prompt_file. Only the prompt file "
        "may change; do not change scoring, runtime code, datasets, or post-processing. "
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

        response = OpenAI(api_key=os.getenv("OPENAI_API_KEY")).chat.completions.create(
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

        response = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")).messages.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text if response.content else ""
        return parse_optimizer_response(text)

    raise ValueError(f"unsupported optimizer provider: {provider}")
