# -*- coding: utf-8 -*-
"""
Step 7. SQL Synthesizer Agent (v2 - LLM Powered)
- Persona: SQL Implementation Engineer
- Task: Synthesize a final, executable PostgreSQL query using the grounded plans from Steps 5 & 6.
- Principle: No hardcoded if-statements for operators. Let LLM handle the final SQL construction based on structured facts.
"""

from __future__ import annotations
import os
import json
import time
from typing import Any, Dict, List

class SqlSynthesizerAgent:
    def __init__(self, cfg):
        self.cfg = cfg

    def main(self, cfg, step1_result, step5_result, step6_result):
        user_query = step1_result.get("user_query", "")
        
        # 1. Prepare the 'Blueprint' for the LLM
        # This includes everything we've confirmed in previous steps.
        blueprint = {
            "target_dialect": "PostgreSQL",
            "logical_intent": user_query,
            "join_structure": {
                "root_table": next((t["table"] for t in step5_result.get("selected_tables", []) if t.get("role") == "root"), None),
                "required_tables": [t["table"] for t in step5_result.get("selected_tables", [])],
                "join_paths": step5_result.get("joins", []),
                "select_columns": step5_result.get("column_bindings", {}) # {physical: table}
            },
            "constraint_logic": {
                "filters": step6_result.get("where_sections", []),
                "ordering": step6_result.get("order_by_section", []),
                "paging": step6_result.get("limit_section", {}),
                "deduplication": step6_result.get("dedupe_section", {})
            }
        }

        # 2. Call LLM to synthesize the final query
        sql_result = self.synthesize_sql(blueprint)

        # 3. Final Result
        return {
            "sql": sql_result.get("sql"),
            "meta": {
                "agent": "7.sql_synthesizer_agent_v2",
                "model": "gpt-4o",
                "timestamp": time.time()
            }
        }

    def synthesize_sql(self, blueprint: Dict[str, Any]) -> Dict[str, str]:
        try:
            from openai import OpenAI
        except ImportError:
            return {"sql": "-- Error: OpenAI SDK missing"}

        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            return {"sql": "-- Synthesis Error: OPENAI_API_KEY is not set"}
        client = OpenAI(api_key=key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")

        system_prompt = (
            "You are a Senior SQL Developer. Your task is to write a clean, efficient PostgreSQL query based on a provided 'Blueprint'.\n\n"
            "### RULES:\n"
            "1. ONLY use the table names, aliases, and column expressions provided in the 'join_structure'.\n"
            "2. Implement the filtering logic strictly as described in 'constraint_logic'.\n"
            "3. For negations (is_negation: true), use appropriate SQL (e.g., NOT IN, !=, IS NOT NULL).\n"
            "4. If deduplication is required, use standard PostgreSQL patterns (e.g., DISTINCT or CTE with ROW_NUMBER if a key is provided).\n"
            "5. Return ONLY a JSON object with a single key 'sql'."
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Blueprint: {json.dumps(blueprint, ensure_ascii=False)}"}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            return {"sql": f"-- Synthesis Error: {str(e)}"}

def main(cfg, step1_result, step5_result, step6_result):
    agent = SqlSynthesizerAgent(cfg)
    return agent.main(cfg, step1_result, step5_result, step6_result)
