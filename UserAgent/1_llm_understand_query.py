# 3_llm_understand_query.py
# Step-3 (LLM-first): Understand / normalise the user's query into a small JSON plan.
# - NO argparse (edit config.py)
# - Does NOT rebuild TTL. Only calls an LLM to rewrite/structure the query.
#
# Output: out/llm_understanding.json
#
# ENV (choose one):
#   Azure OpenAI:
#     AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT, (optional) AZURE_OPENAI_API_VERSION
#   OpenAI-compatible:
#     OPENAI_API_KEY, (optional) OPENAI_BASE_URL, (optional) OPENAI_MODEL

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict
import urllib.request

#from config import CFG
from common_io import dump_json


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def call_llm_json(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """
    Supports:
      1) Azure OpenAI Chat Completions
      2) OpenAI-compatible Chat Completions

    Returns a dict parsed from LLM JSON output.
    """
    # ---- Azure OpenAI ----
    az_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    az_key = os.getenv("AZURE_OPENAI_API_KEY")
    az_deploy = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    az_ver = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    if az_endpoint and az_key and az_deploy:
        url = f"{az_endpoint.rstrip('/')}/openai/deployments/{az_deploy}/chat/completions?api-version={az_ver}"
        headers = {"Content-Type": "application/json", "api-key": az_key}
        payload = {
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        res = _post_json(url, headers, payload)
        content = res["choices"][0]["message"]["content"]
        return json.loads(content)

    # ---- OpenAI-compatible ----
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    if key:
        url = f"{base.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        payload = {
            "model": model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        res = _post_json(url, headers, payload)
        content = res["choices"][0]["message"]["content"]
        return json.loads(content)

    raise RuntimeError(
        "No LLM credentials found. Set either AZURE_OPENAI_* env vars or OPENAI_API_KEY (and optionally OPENAI_BASE_URL/OPENAI_MODEL)."
    )


SYSTEM_PROMPT = r"""
You are a Korean query-understanding assistant for financial data.
Your job is to rewrite and structure the user query WITHOUT inventing new domain terms.
You must not add new columns or values that do not appear in the input text.

Return ONLY valid JSON (no markdown).

Schema:
  "normalized_query": "string",          // rewritten query
  "primary_subject_anchor": "string",    // the central business entity (e.g., 계좌, 상품, 권한, 사용자) that penetrates this query
  "anchor_reasoning": "string",          // why this anchor was chosen as the primary subject
  "targets": ["string", ...],            // what to retrieve
  "field_phrases": ["string", ...],      // likely field phrases
  "value_phrases": ["string", ...],      // raw values
  "conditions_text": ["string", ...],    // condition fragments
  "scope_text": ["string", ...],         // scope fragments
  "ambiguous_phrases": ["string", ...]   // ambiguous phrases
}
"""


def main(cfg):
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    user_query = cfg.sample_query

    user_prompt = f"""
User query:
{user_query}

Please output the JSON schema exactly.
Notes:
- Keep Korean words as-is; you may remove particles like 가/을/를/은/는/의 when rewriting normalized_query.
- Do NOT guess business meaning (e.g. do NOT convert "사용 중" into a code like "정상"). Put such phrases into ambiguous_phrases.
"""

    parsed = call_llm_json(SYSTEM_PROMPT, user_prompt)

    # Minimal safety defaults
    for k in ["normalized_query", "primary_subject_anchor", "anchor_reasoning", "targets", "field_phrases", "value_phrases", "conditions_text", "scope_text", "ambiguous_phrases"]:
        if k not in parsed:
            parsed[k] = "" if k in ["normalized_query", "primary_subject_anchor", "anchor_reasoning"] else []

    out = {
        "meta": {
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "source": "LLM",
        },
        "inputQuery": user_query,
        "parsed": parsed,
    }
    return out
    #dump_json(out, cfg.out_dir / "llm_understanding.json")
    #print("Wrote:", cfg.out_dir / "llm_understanding.json")


#if __name__ == "__main__":
#    main()
