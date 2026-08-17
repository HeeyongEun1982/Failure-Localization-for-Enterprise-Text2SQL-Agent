# -*- coding: utf-8 -*-
"""
Step 5.5. Join Semantic Verifier Agent
- Role: SQL Architect & Data Governance Analyst
- Task: Review the join edges generated in Step 5 and verify if they are semantically correct.
- Goal: Prevent incorrect joins (e.g., joining an 'ID' with an 'Employee Number' just because they are integers).
"""

from __future__ import annotations
import os
import json
import time
from typing import Any, Dict, List

class JoinSemanticVerifierAgent:
    def __init__(self, cfg):
        self.cfg = cfg

    def main(self, cfg, step1_result: Dict[str, Any], step5_result: Dict[str, Any], semantic_catalog: Dict[str, Any]):
        user_query = step1_result.get("user_query", "")
        joins = step5_result.get("joins", [])
        
        if not joins:
            return step5_result

        # Identify roles of tables involved in joins
        relevant_catalog = {}
        for j in joins:
            for t in [j["from"], j["to"]]:
                if t in semantic_catalog:
                    relevant_catalog[t] = semantic_catalog[t]

        # 1. Prepare Verification Context with Semantic Catalog
        verification_plan = {
            "user_intent": user_query,
            "proposed_joins": joins,
            "table_semantic_roles": relevant_catalog,
            "column_metadata_hint": "Examine if the join semantic roles (e.g. MASTER vs HISTORY) and subjects match logically."
        }

        # 2. Call LLM for Semantic Verification
        verification_result = self.call_llm_for_verification(verification_plan)

        # 3. Apply Corrections
        # If the LLM found errors, we log them. For now, we'll mark them in the plan.
        # In a more advanced version, we could ask the LLM to suggest the correct column.
        verified_joins = []
        for j in joins:
            # Match the join in the LLM response
            # Note: Robust matching could be done by from/to/cols
            analysis = self._find_analysis(j, verification_result.get("analysis", []))
            
            j_copy = dict(j)
            if analysis:
                j_copy["semantic_valid"] = analysis.get("is_valid", True)
                j_copy["semantic_rationale"] = analysis.get("rationale", "")
                if not analysis.get("is_valid") and analysis.get("corrected_to_col"):
                    # Proactively correct the join column if suggested
                    j_copy["to_col"] = analysis.get("corrected_to_col")
                    j_copy["was_corrected"] = True
            
            verified_joins.append(j_copy)

        step5_result["joins"] = verified_joins
        step5_result["meta"]["semantic_verified"] = True
        step5_result["meta"]["verifier_agent"] = "5.5_join_semantic_verifier"
        
        return step5_result

    def _find_analysis(self, join_edge, analyses):
        for a in analyses:
            if (a.get("from") == join_edge["from"] and a.get("to") == join_edge["to"] and 
                a.get("from_col") == join_edge["from_col"] and a.get("to_col") == join_edge["to_col"]):
                return a
        return None

    def call_llm_for_verification(self, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError:
            return {"analysis": []}

        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            return {"analysis": []}
        client = OpenAI(api_key=key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")

        system_prompt = (
            "You are a Data Governance Expert. You verify JOIN conditions in SQL query plans.\n"
            "Graph-based algorithms sometimes join columns incorrectly because they have similar names or data types.\n"
            "Your task is to identify if a join between two columns is SEAMNTICALLY CORRECT based on the entity types.\n\n"
            "Example Error:\n"
            "- Join: bs1003.aprvln_id = bs1002.hrk_aprv_ep_no\n"
            "- Logic: 'aprvln_id' is a Line ID, 'hrk_aprv_ep_no' is an Employee Number. They are NOT the same entity. This join is WRONG.\n\n"
            "Output Format (JSON):\n"
            "{\n"
            "  \"analysis\": [\n"
            "    {\n"
            "      \"from\": \"table1\", \"to\": \"table2\", \"from_col\": \"col1\", \"to_col\": \"col2\",\n"
            "      \"is_valid\": false, \n"
            "      \"rationale\": \"Explanation of why it is correct or incorrect\",\n"
            "      \"corrected_to_col\": \"Optional: suggest the correct column name in table2 if you know the schema or can infer it\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Review these joins for user intent: {json.dumps(context, ensure_ascii=False)}"}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )
            return json.loads(response.choices[0].message.content)
        except Exception:
            return {"analysis": []}

def main(cfg, step1_result, step5_result, semantic_catalog):
    verifier = JoinSemanticVerifierAgent(cfg)
    return verifier.main(cfg, step1_result, step5_result, semantic_catalog)
