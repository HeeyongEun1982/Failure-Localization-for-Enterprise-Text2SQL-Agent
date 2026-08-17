# -*- coding: utf-8 -*-
"""
Step 5. Semantic Table Linking Engine (v4.3 - Coverage-Aware Rooting)
- Logic:
  1. Map columns to candidate tables.
  2. Compute "Root Score" for each table based on:
     - Coverage: How many requested columns does it have? (Primary Factor)
     - Subject: Does it match the query's primary subject?
     - Tier: Is it a Master or Transaction table?
  3. Select the best scorer as the Search Root.
  4. Build the join path to cover remaining columns.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Set, Optional, Any, Tuple, Deque
from collections import defaultdict, deque

def fold(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "")

@dataclass(frozen=True)
class JoinEdge:
    frm: str
    to: str
    frm_col: str
    to_col: str
    def as_dict(self) -> Dict[str, Any]:
        return {"from": self.frm, "to": self.to, "from_col": self.frm_col, "to_col": self.to_col}

class TableLinkingEngine:
    def __init__(self):
        self.reasoning = []

    def _log(self, msg: str):
        print(f" [DEBUG] {msg}")
        self.reasoning.append(msg)

    def main(self, step1_result: Dict[str, Any], step4_result: Dict[str, Any], col_to_tabs: Dict[str, List[Any]], jgraph: Dict[str, Any], hierarchy: Dict[str, Any]):
        self.reasoning = []
        
        # 1. Extraction
        confirmed = step4_result.get("confirmed", {})
        terms = confirmed.get("terms", [])
        needed_cols = set()
        for t in terms:
            phys = fold(t.get("physicalName", ""))
            if phys: needed_cols.add(phys)
        
        if not needed_cols:
            self._log("No physical columns identified.")
            return {"error": "No physical columns identified.", "reasoning": ["Input column list was empty."]}

        # 2. Inverted Index
        col_dist = defaultdict(set)
        all_candidate_tables = set()
        for col in needed_cols:
            entries = col_to_tabs.get(col, [])
            for ent in entries:
                t_name = fold(ent.get("table", "")) if isinstance(ent, dict) else fold(str(ent))
                if t_name and not t_name.startswith("_"): 
                    col_dist[col].add(t_name)
                    all_candidate_tables.add(t_name)
        
        self._log(f"Step 1: Found {len(all_candidate_tables)} unique tables containing requested columns.")

        # 3. ADVANCED ROOT SCORING
        # "단순 주체성보다 데이터보유량(Coverage)이 더 중요합니다."
        parsed_llm = step1_result.get("parsed", {})
        query_subject = fold(parsed_llm.get("primary_subject_anchor", ""))
        semantic_catalog = hierarchy.get("semantic_catalog", {})
        tiers = hierarchy.get("table_tiers", {})
        
        table_scores = []
        for tab in all_candidate_tables:
            score = 0
            # A. Coverage Score (Most Important)
            coverage_count = sum(1 for c in needed_cols if tab in col_dist[c])
            score += (coverage_count * 100)
            
            # B. Subject Match Score
            cat = semantic_catalog.get(tab, {})
            tab_subject = fold(cat.get("subject", ""))
            if query_subject and query_subject in tab_subject:
                score += 150 # Strong bonus for semantic alignment
                if cat.get("role") == "MASTER":
                    score += 50 # Bonus for being the master of that subject
            
            # C. Tier Bonus
            tier = tiers.get(tab, 2)
            if tier == 1: score += 30
            
            table_scores.append((score, tab, coverage_count))
            self._log(f"  - Table '{tab}': Score={score} (Coverage={coverage_count}/{len(needed_cols)}, SubjectMatch={'Y' if query_subject in tab_subject else 'N'})")

        table_scores.sort(key=lambda x: x[0], reverse=True)
        search_root = table_scores[0][1] if table_scores else None

        if not search_root:
            self._log("Step 2 CRITICAL: Failed to identify any root table.")
            return {"error": "Root identification failed.", "reasoning": self.reasoning}

        self._log(f"Step 2 Result: Chosen ROOT = '{search_root}' based on highest score.")

        # 4. Connected Coverage (Steiner-Tree style)
        adj = defaultdict(list)
        table_pks = defaultdict(set)
        for src_raw, rels in (jgraph or {}).items():
            src = fold(src_raw)
            for r in (rels or []):
                dst, f_c, t_c = fold(r["to"]), fold(r["from_column"]), fold(r["to_column"])
                table_pks[dst].add(t_c)
                adj[src].append(JoinEdge(src, dst, f_c, t_c))
                adj[dst].append(JoinEdge(dst, src, t_c, f_c))

        final_tables = {search_root}
        final_joins = []
        col_bindings = {}
        remaining_cols = set(needed_cols)
        
        # Priority 1: Direct Coverage
        for c in remaining_cols.copy():
            if search_root in col_dist[c]:
                col_bindings[c] = search_root
                remaining_cols.remove(c)
                self._log(f"Step 3: Column '{c}' bound to Root '{search_root}'.")

        # Priority 2: Seek missing via JGraph
        # Dynamically derive potential join columns from the entire join graph
        # These are columns the metadata says are valid for joining.
        JOINABLE_COLS = set()
        for rels in (jgraph or {}).values():
            for r in (rels or []):
                JOINABLE_COLS.add(fold(r.get("from_column", "")))
                JOINABLE_COLS.add(fold(r.get("to_column", "")))
        
        for col in sorted(list(remaining_cols)):
            best_path = None
            target_table = None
            
            # A. Try Explicit Graph Path
            for start_node in list(final_tables):
                for candidate_table in col_dist[col]:
                    path = self._bfs_path(adj, table_pks, start_node, candidate_table)
                    if path is not None:
                        if best_path is None or len(path) < len(best_path):
                            best_path = path
                            target_table = candidate_table
            
            if best_path is not None:
                self._log(f"Step 3: Found explicit path for '{col}' via {target_table}")
                for edge in best_path:
                    if edge.to not in final_tables:
                        final_joins.append(edge.as_dict())
                        final_tables.add(edge.to)
                col_bindings[col] = target_table
                continue

            # B. Fallback: Try Implicit Join (Using Joinable Columns found in Graph)
            found_implicit = False
            for start_node in list(final_tables):
                for candidate_table in col_dist[col]:
                    shared_keys = []
                    # Check common columns that are known to be joinable in this domain
                    for bkey in JOINABLE_COLS:
                        if not bkey: continue
                        mappings = col_to_tabs.get(bkey, [])
                        has_start = any(fold(m.get("table", "")) == start_node for m in mappings if isinstance(m, dict))
                        has_cand = any(fold(m.get("table", "")) == candidate_table for m in mappings if isinstance(m, dict))
                        if has_start and has_cand:
                            shared_keys.append(bkey)
                    
                    if shared_keys:
                        # Tie-break: prioritize keys like 'acno', 'cif' if multiple (optional heuristic)
                        chosen_key = shared_keys[0]
                        self._log(f"Step 3 SUCCESS: Found Implicit Join for '{col}' via key '{chosen_key}' between {start_node} and {candidate_table}")
                        final_joins.append({
                            "from": start_node,
                            "to": candidate_table,
                            "from_col": chosen_key,
                            "to_col": chosen_key,
                            "semantic_verified": True,
                            "rationale": f"Implicit join via metadata-derived join key: {chosen_key}"
                        })
                        final_tables.add(candidate_table)
                        col_bindings[col] = candidate_table
                        found_implicit = True
                        break

                if found_implicit: break

            if not found_implicit:
                self._log(f"Step 3 FAILURE: Column '{col}' remains unreachable from Root cluster.")

        missing = [c for c in needed_cols if c not in col_bindings]

        return {
            "root_anchor": search_root,
            "selected_tables": [
                {
                    "table": t, 
                    "tier": tiers.get(t, 2), 
                    "role": "root" if t == search_root else "bridge"
                } for t in sorted(final_tables)
            ],
            "joins": final_joins,
            "column_bindings": col_bindings,
            "reasoning": self.reasoning,
            "diagnostics": {
                "subject": query_subject,
                "missing_columns": missing,
                "scores": {tab: score for score, tab, _ in table_scores[:5]}
            }
        }

    def _bfs_path(self, adj, table_pks, start, goal) -> Optional[List[JoinEdge]]:
        if start == goal: return []
        q = deque([start])
        visited = {start}
        parent = {}
        while q:
            cur = q.popleft()
            for edge in adj.get(cur, []):
                if edge.to not in visited:
                    # Allow non-PK joins to increase reachability
                    visited.add(edge.to)
                    parent[edge.to] = edge
                    if edge.to == goal:
                        res = []
                        curr = goal
                        while curr != start:
                            e = parent[curr]
                            res.append(e)
                            curr = e.frm
                        return res[::-1]
                    q.append(edge.to)
        return None


def main(step1_result, step4_result, col_to_tabs, jgraph, hierarchy):
    engine = TableLinkingEngine()
    return engine.main(step1_result, step4_result, col_to_tabs, jgraph, hierarchy)
