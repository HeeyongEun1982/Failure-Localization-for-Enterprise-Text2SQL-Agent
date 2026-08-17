# 5_final_select_v2.py
# Rule-based final selection (generic) with an override for exact Korean term match.
# - NO argparse
# - No domain hardcoding: the override is purely string-equality between surface and candidate.originalTerm.
#
# Input : out/step1_summary_llm.json
# Output: out/step1_summary_llm_final.json

from __future__ import annotations

from typing import Any, Dict, List, Optional

from common_io import load_json, dump_json
from common_text import normalize
#from config import CFG


# Tunables
MAX_CANDIDATES_DROP = 12
MIN_SURFACE_LEN_KEEP = 2


def token_count(physical_name: str) -> int:
    return len([t for t in physical_name.split("_") if t])


def _surface_key(s: str) -> str:
    # normalize then remove whitespace for robust equality
    return normalize(s).replace(" ", "")


def choose_best_candidate(surface: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Selection strategy:
    0) HIGH-CONFIDENCE OVERRIDE (generic):
       if any candidate.originalTerm exactly equals surface (after whitespace removal),
       choose it (even if many candidates).
    1) Otherwise choose most generic by:
       - minimal underscore token_count
       - tie-break by shortest string length
    """
    valid = [c for c in candidates if (c.get("physicalName") or "").strip()]
    if not valid:
        return None

    skey = _surface_key(surface)
    exact = []
    for c in valid:
        oterm = (c.get("originalTerm") or "").strip()
        if oterm and _surface_key(oterm) == skey:
            exact.append(c)

    if exact:
        # if multiple exact (rare), pick shortest physicalName
        exact.sort(key=lambda c: (token_count(c["physicalName"]), len(c["physicalName"])))
        chosen = exact[0]
        chosen["_selectionRule"] = "EXACT_ORIGINALTERM_MATCH_OVERRIDE"
        return chosen

    valid.sort(key=lambda c: (token_count(c["physicalName"]), len(c["physicalName"])))
    chosen = valid[0]
    chosen["_selectionRule"] = "MIN_UNDERSCORE_TOKENS_THEN_MIN_LEN"
    return chosen


def main(cfg, summary_llm):
    #CFG.out_dir.mkdir(parents=True, exist_ok=True)

    data = summary_llm
    #data = load_json(CFG.out_dir / "step1_summary_llm.json")
    term_mentions = data.get("termMentions", [])

    final_mentions = []
    dropped = []

    for m in term_mentions:
        surface = m.get("surface") or ""
        cands = m.get("candidates") or []
        cand_count = len(cands)

        if cand_count == 0:
            dropped.append({**m, "dropReason": "NO_CANDIDATES"})
            continue

        # Rule-based selection: always keep the best match if any candidates exist.
        best = choose_best_candidate(surface, cands)
        if not best:
            dropped.append({**m, "dropReason": "NO_VALID_PHYSICALNAME"})
            continue

        used_rule = best.pop("_selectionRule", "MIN_UNDERSCORE_TOKENS_THEN_MIN_LEN")

        final_mentions.append({
            **m,
            "finalSelection": {
                "physicalName": best.get("physicalName"),
                "originalTerm": best.get("originalTerm"),
                "hierarchy": best.get("hierarchy"),
                "selectionRule": used_rule,
                "candidateCount": cand_count,
            }
        })


    out = {
        **data,
        "finalSelections": {
            "termMentionsSelected": final_mentions,
            "termMentionsDropped": dropped,
            "notes": [
                "Final selection is rule-based (no domain hardcoding).",
                f"Drop rules apply unless exact originalTerm match override is used: cand_count>{MAX_CANDIDATES_DROP} OR (norm_surface_len<={MIN_SURFACE_LEN_KEEP} AND cand_count>1).",
                "Selection rules: (a) EXACT_ORIGINALTERM_MATCH_OVERRIDE, else (b) MIN_UNDERSCORE_TOKENS_THEN_MIN_LEN.",
            ]
        }
    }

    return out

    #dump_json(out, CFG.out_dir / "step1_summary_llm_final.json")
    #print("Wrote:", CFG.out_dir / "step1_summary_llm_final.json")


#if __name__ == "__main__":
#    main()
