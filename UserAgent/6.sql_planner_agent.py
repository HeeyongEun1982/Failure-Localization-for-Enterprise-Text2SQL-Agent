# -*- coding: utf-8 -*-
"""
Step 6. SQL Planner Agent (v3 - Sectional Logic Designer)
- Persona: SQL Query Logic Designer
- Task: Decompose the natural language query into specific SQL logical sections.
- Focus: High-precision extraction of filtering, ordering, and paging logic.

Patch notes (2026-02-22):
- Accepts Step-4 outputs in BOTH formats:
  (A) {"confirmed": {"terms": [...], "codes": [...]}}
  (B) the v4 JSON like 4_result.json with {"finalSelections": {"termMentionsSelected": [...]}, "codeMentions": [...]}
- Removes hardcoded API key. Uses OPENAI_API_KEY env or cfg["openai_api_key"].
- Never returns an empty plan: if LLM is unavailable, returns a deterministic fallback plan
  based on codeMentions + simple negation parsing.
"""

from __future__ import annotations

import os
import json
import time
import re
from typing import Any, Dict, List, Optional, Tuple


class SqlPlannerAgent:
    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        # Default negation markers for Korean/English heuristic fallback
        self.default_neg_markers = ["아닌", "아니고", "제외", "not", "NOT", "없", "않"]

    def main(self, cfg, step1_result, step4_result, step5_result, semantic_catalog: Dict[str, Any] = None):
        cfg = cfg or self.cfg or {}
        user_query = (step1_result or {}).get("user_query") or (step4_result or {}).get("inputQuery") or ""

        terms, codes = self._extract_terms_codes(step4_result or {})
        col_bindings = (step5_result or {}).get("column_bindings", {}) or {}

        # Normalize column bindings keys (case-insensitive)
        col_bindings_lower = {str(k).strip().lower(): v for k, v in col_bindings.items()}

        # 1) Available Column & Code Context (Semantic Grounding)
        binding_pool: List[Dict[str, Any]] = []
        for t in terms:
            physical = (t.get("physicalName") or "").strip()
            if not physical:
                continue
            physical_l = physical.lower()
            table = col_bindings_lower.get(physical_l, "") or ""
            
            # Semantic Context from Catalog
            catalog_entry = (semantic_catalog or {}).get(table, {})

            matching_codes = [
                {"label": c.get("label"), "code": c.get("code")}
                for c in codes
                if (c.get("physicalName") or "").strip().lower() == physical_l
            ]

            binding_pool.append(
                {
                    "logical_concept": t.get("originalTerm") or t.get("surface") or "",
                    "user_term": t.get("surface", ""),
                    "column_physical": physical_l,
                    "table_alias": table,
                    "table_role": catalog_entry.get("role", "UNKNOWN"),
                    "table_subject": catalog_entry.get("subject", "UNKNOWN"),
                    "full_expr": f"{table}.{physical_l}" if table else physical_l,
                    "potential_values": matching_codes,
                }
            )

        # 2) Sectional Logic Extraction via LLM (or fallback)
        plan = self.design_sql_logic(user_query, binding_pool, codes)

        # 3) Final Metadata (always present)
        if not isinstance(plan, dict):
            plan = {}

        plan.setdefault("where_sections", [])
        plan.setdefault("order_by_section", [])
        plan.setdefault("limit_section", {"count": None, "matched_snippet": ""})
        plan.setdefault("dedupe_section", {"key_column": None, "policy": None, "matched_snippet": ""})

        plan["meta"] = {
            "agent": "6.sql_planner_agent_v3.2",
            "persona": "SQL_Logic_Designer",
            "timestamp": time.time(),
            "binding_pool_size": len(binding_pool),
        }
        return plan

    # -------------------------
    # Step-4 format adapters
    # -------------------------
    def _extract_terms_codes(self, step4_result: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Returns:
          terms: list of {"surface", "originalTerm", "physicalName"}
          codes: list of {"physicalName", "label", "code", "sourceText"}
        """
        # Format A: {"confirmed": {"terms": [...], "codes": [...]} }
        confirmed = step4_result.get("confirmed")
        if isinstance(confirmed, dict):
            terms = confirmed.get("terms") or []
            codes = confirmed.get("codes") or []
            # Ensure surfaces exist
            norm_terms = []
            for t in terms:
                if not isinstance(t, dict):
                    continue
                norm_terms.append(
                    {
                        "surface": t.get("surface") or t.get("user_term") or "",
                        "originalTerm": t.get("originalTerm") or "",
                        "physicalName": t.get("physicalName") or "",
                    }
                )
            norm_codes = []
            for c in codes:
                if not isinstance(c, dict):
                    continue
                norm_codes.append(
                    {
                        "physicalName": c.get("physicalName") or "",
                        "label": c.get("label") or "",
                        "code": c.get("code"),
                        "sourceText": c.get("sourceText") or "",
                    }
                )
            return norm_terms, norm_codes

        # Format B: v4 style like 4_result.json
        final_selections = step4_result.get("finalSelections") or {}
        selected = []
        if isinstance(final_selections, dict):
            selected = final_selections.get("termMentionsSelected") or []

        norm_terms: List[Dict[str, Any]] = []
        for item in selected:
            if not isinstance(item, dict):
                continue
            fs = item.get("finalSelection") or {}
            if not isinstance(fs, dict):
                continue
            norm_terms.append(
                {
                    "surface": item.get("surface") or item.get("sourceText") or "",
                    "originalTerm": fs.get("originalTerm") or "",
                    "physicalName": fs.get("physicalName") or "",
                }
            )

        norm_codes: List[Dict[str, Any]] = []
        for c in (step4_result.get("codeMentions") or []):
            if not isinstance(c, dict):
                continue
            norm_codes.append(
                {
                    "physicalName": c.get("physicalName") or "",
                    "label": c.get("label") or "",
                    "code": c.get("code"),
                    "sourceText": c.get("sourceText") or "",
                }
            )

        return norm_terms, norm_codes

    # -------------------------
    # Planner core
    # -------------------------
    def design_sql_logic(self, query: str, pool: List[Dict[str, Any]], codes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Preferred: LLM-based JSON planning.
        Fallback: deterministic plan from codeMentions + simple negation patterns.
        """
        # If no available columns, still try fallback (never return empty)
        llm = self._try_llm_plan(query, pool)
        if isinstance(llm, dict) and not llm.get("error"):
            return llm

        fallback = self._fallback_plan(query, pool, codes)
        if isinstance(llm, dict) and llm.get("error"):
            fallback.setdefault("diagnostics", {})
            fallback["diagnostics"]["llm_error"] = llm.get("error")
        return fallback

    def _try_llm_plan(self, query: str, pool: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Require SDK + API key; otherwise return an error and let fallback kick in
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            return {"error": "OpenAI SDK missing"}

        key = os.getenv("OPENAI_API_KEY") or cfg.get("openai_api_key")
        if not key:
            return {"error": "OPENAI_API_KEY is not set"}

        client = OpenAI(api_key=key)
        model = "gpt-4o"

        system_prompt = (
            "You are a 'SQL Query Logic Designer'. Translate the user's intent into structured SQL logic sections.\n"
            "Use ONLY the provided full_expr values when you reference columns.\n\n"
            "Return STRICT JSON with these keys: where_sections, order_by_section, limit_section, dedupe_section.\n"
            "where_sections is a list of filters; each filter must include matched_snippet.\n"
            "Operators: EQ, NEQ, IN, NOT_IN, GT, LT, IS_NULL, IS_NOT_NULL.\n"
            "Pay extreme attention to negations like '아닌', '제외', 'not' -> use NEQ/NOT_IN.\n"
        )

        user_input = {"user_intent": query, "available_columns": pool}

        json_format = {
            "where_sections": [
                {
                    "column": "table.column",
                    "operator": "NOT_IN",
                    "values": ["VALUE_A", "VALUE_B"],
                    "is_negation": True,
                    "matched_snippet": "TEXT_INDICATING_NEGATION",
                }
            ],
            "order_by_section": [{"column": "table.column", "direction": "DESC", "matched_snippet": "TEXT_INDICATING_SORT"}],
            "limit_section": {"count": 10, "matched_snippet": "TEXT_INDICATING_LIMIT"},
            "dedupe_section": {"key_column": "table.column", "policy": "LATEST", "matched_snippet": "TEXT_INDICATING_DEDUPE"},
        }

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Design SQL logic for this intent: {json.dumps(user_input, ensure_ascii=False)}\n"
                            f"Format: {json.dumps(json_format, ensure_ascii=False)}"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = response.choices[0].message.content
            return json.loads(content) if content else {"error": "Empty LLM response"}
        except Exception as e:
            return {"error": str(e)}

    def _fallback_plan(self, query: str, pool: List[Dict[str, Any]], codes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Heuristic plan:
        - Groups code mentions by physicalName.
        - If the query contains negation markers around the mention's sourceText,
          use NOT_IN, else IN.
        - Tries to pick the most plausible column expression from pool; if missing,
          falls back to physicalName.lower().
        """
        # Build a helper: physicalName -> best full_expr
        phys_to_expr: Dict[str, str] = {}
        for p in pool:
            phys = (p.get("column_physical") or "").strip().lower()
            expr = (p.get("full_expr") or "").strip()
            if phys and expr and phys not in phys_to_expr:
                phys_to_expr[phys] = expr

        # Group codes by physicalName
        by_phys: Dict[str, List[Dict[str, Any]]] = {}
        for c in codes:
            phys = (c.get("physicalName") or "").strip().lower()
            if not phys:
                continue
            by_phys.setdefault(phys, []).append(c)

        # Restrict to physical names that are actually selected/available in this step.
        # (4_result.json often contains many codeMentions for other similar code columns.)
        allowed_phys = set(phys_to_expr.keys())
        by_phys = {k: v for k, v in by_phys.items() if k in allowed_phys}

        neg_markers = self.cfg.get("neg_markers", self.default_neg_markers)

        where_sections: List[Dict[str, Any]] = []

        for phys, items in by_phys.items():
            # Decide negation: if any snippet appears near negation marker in the query
            # (simple but effective for Korean patterns like "~가 ... 아니고")
            joined_source = " ".join({(it.get("sourceText") or "") for it in items if it.get("sourceText")})
            is_neg = any(m in query for m in neg_markers) and ("아니" in query or "not" in query.lower())

            # Choose operator: typical in your example is NOT_IN
            op = "NOT_IN" if is_neg else "IN"

            # If the query explicitly says "<LABEL>가 아닌/아니고", treat only that label as excluded/included.
            item_labels = {(it.get("label") or "").strip() for it in items if (it.get("label") or "").strip()}
            explicit_tokens = re.findall(r"([0-9A-Za-z가-힣_()]+)\s*가\s*(?:아닌|아니고)", query)
            explicit_labels = [t for t in explicit_tokens if t in item_labels]
            # values
            vals = []
            if explicit_labels:
                # Only the explicitly-negated labels
                for it in items:
                    label = (it.get("label") or "").strip()
                    if label in explicit_labels:
                        vals.append(it.get("code") if it.get("code") is not None else label)
            else:
                # Otherwise, include all mentioned items for this physicalName
                for it in items:
                    if it.get("code") is not None:
                        vals.append(it.get("code"))
                    elif it.get("label"):
                        vals.append(it.get("label"))

            # If no label-level negation was detected (e.g., a list followed by '...상태가 아니고'),
            # include all mentioned items for this physicalName.
            if not vals:
                for it in items:
                    if it.get("code") is not None:
                        vals.append(it.get("code"))
                    elif it.get("label"):
                        vals.append(it.get("label"))

            # De-dup while preserving order
            seen = set()
            vals2 = []
            for v in vals:
                if v in seen:
                    continue
                seen.add(v)
                vals2.append(v)

            # matched snippet: pick the shortest meaningful sourceText
            snippets = [it.get("sourceText") for it in items if it.get("sourceText")]
            matched_snippet = min(snippets, key=len) if snippets else phys

            where_sections.append(
                {
                    "column": phys_to_expr.get(phys, phys),
                    "operator": op,
                    "values": vals2,
                    "is_negation": op in ("NEQ", "NOT_IN"),
                    "matched_snippet": matched_snippet,
                }
            )

        # If user asked output fields like 온라인 사용자 ID / 계좌번호, you may want to dedupe by user id
        # but planner keeps it optional; leave empty unless clearly specified.
        return {
            "where_sections": where_sections,
            "order_by_section": [],
            "limit_section": {"count": None, "matched_snippet": ""},
            "dedupe_section": {"key_column": None, "policy": None, "matched_snippet": ""},
            "diagnostics": {
                "mode": "fallback",
                "note": "LLM unavailable or failed; planned using codeMentions + simple negation parsing.",
            },
        }


def main(cfg, step1_result, step4_result, step5_result, semantic_catalog=None):
    planner = SqlPlannerAgent(cfg)
    return planner.main(cfg, step1_result, step4_result, step5_result, semantic_catalog)
