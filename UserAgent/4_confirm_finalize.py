# 6_confirm_finalize_v2.py
# Confirm & finalize Step1 selections AND produce a confirmed-only minimal output.
#
# Input : out/step1_summary_llm_final.json
#         out/ttl_code_index.json
#         out/term_lexicon.json
# Output:
#   - out/step1_confirmed.json          (full, with rejected/dropped/diagnostics)
#   - out/step1_confirmed_only.json     (ONLY confirmed term selections + confirmed code mentions)
#
# Confirmation rules:
# - CONFIRMED only if physicalName exists in BOTH:
#     (1) CSV lexicon records
#     (2) TTL physicalToTerm map
# - Code mentions are kept only if their physicalName is CONFIRMED

from __future__ import annotations

from typing import Any, Dict, List

from common_io import load_json, dump_json
#from config import CFG



def _build_csv_set(term_lex: Dict[str, Any]) -> set:
    s = set()
    for r in term_lex.get("records", []):
        pn = (r.get("physicalName") or "").strip()
        if pn:
            s.add(pn)
    return s


def main(cfg, summary_llm_final, ttl_idx, term_lex):
    #CFG.out_dir.mkdir(parents=True, exist_ok=True)
    inp = summary_llm_final
    #inp = load_json(CFG.out_dir / "step1_summary_llm_final.json")
    #ttl_idx = load_json(CFG.out_dir / "ttl_code_index.json")
    #term_lex = load_json(CFG.out_dir / "term_lexicon.json")

    csv_phys = _build_csv_set(term_lex)
    ttl_phys_to_term: Dict[str, str] = ttl_idx.get("physicalToTerm", {})
    ttl_term_to_codes: Dict[str, Dict[str, Dict[str, str]]] = ttl_idx.get("termToCodes", {})

    fs = inp.get("finalSelections", {})
    selected_mentions = fs.get("termMentionsSelected", [])
    dropped_mentions = fs.get("termMentionsDropped", [])

    confirmed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    confirmed_phys = set()

    for m in selected_mentions:
        sel = (m.get("finalSelection") or {})
        pn = (sel.get("physicalName") or "").strip()

        reasons = []
        if not pn:
            reasons.append("EMPTY_PHYSICALNAME")
        if pn and pn not in csv_phys:
            reasons.append("NOT_IN_CSV_LEXICON")
        term_id = ttl_phys_to_term.get(pn) if pn else None
        if pn and not term_id:
            reasons.append("NOT_IN_TTL_INDEX")

        if reasons:
            rejected.append({**m, "confirm": {"status": "REJECTED", "reasons": reasons}})
            continue

        confirmed_phys.add(pn)
        confirmed.append({
            **m,
            "confirm": {
                "status": "CONFIRMED",
                "termId": term_id,
                "hasCodeList": bool(ttl_term_to_codes.get(term_id)),
            }
        })

    # Code filtering
    code_mentions_in = inp.get("codeMentions", [])
    code_mentions_ok: List[Dict[str, Any]] = []
    code_mentions_dropped: List[Dict[str, Any]] = []

    for cm in code_mentions_in:
        pn = (cm.get("physicalName") or "").strip()
        term_id = cm.get("termId")
        code = (cm.get("code") or "").strip()
        label = (cm.get("label") or "").strip()

        if pn not in confirmed_phys:
            code_mentions_dropped.append({**cm, "dropReason": "TERM_NOT_CONFIRMED"})
            continue

        cmap = ttl_term_to_codes.get(term_id or "", {})
        ok = False
        if cmap:
            for info in cmap.values():
                if info.get("code") == code and info.get("label") == label:
                    ok = True
                    break
        else:
            ok = True

        if ok:
            code_mentions_ok.append({**cm, "confirm": {"status": "CONFIRMED"}})
        else:
            code_mentions_dropped.append({**cm, "dropReason": "CODE_NOT_IN_TTL_CODELIST"})

    full_out = {
        "inputQuery": inp.get("inputQuery"),
        "llmUnderstanding": inp.get("llmUnderstanding"),
        "confirmed": {"termMentions": confirmed, "codeMentions": code_mentions_ok},
        "rejected": {"termMentions": rejected, "codeMentions": code_mentions_dropped},
        "droppedEarlier": {"termMentions": dropped_mentions, "unresolvedMentions": inp.get("unresolvedMentions", [])},
        "diagnostics": {
            "counts": {
                "selectedInStep5": len(selected_mentions),
                "confirmedTerms": len(confirmed),
                "rejectedTerms": len(rejected),
                "inputCodeMentions": len(code_mentions_in),
                "confirmedCodes": len(code_mentions_ok),
                "droppedCodes": len(code_mentions_dropped),
                "droppedEarlierTerms": len(dropped_mentions),
                "unresolved": len(inp.get("unresolvedMentions", [])),
            }
        }
    }

    # Minimal confirmed-only output (what you wanted)
    minimal_out = {
        "inputQuery": inp.get("inputQuery"),
        "confirmed": {
            "terms": [
                {
                    "physicalName": (m.get("finalSelection") or {}).get("physicalName"),
                    "termId": (m.get("confirm") or {}).get("termId"),
                    "surface": m.get("surface"),
                    "selectionRule": (m.get("finalSelection") or {}).get("selectionRule"),
                }
                for m in confirmed
            ],
            "codes": [
                {
                    "physicalName": cm.get("physicalName"),
                    "termId": cm.get("termId"),
                    "code": cm.get("code"),
                    "label": cm.get("label"),
                    "sourceText": cm.get("sourceText"),
                }
                for cm in code_mentions_ok
            ],
            "unresolved": inp.get("unresolvedMentions", []),
        }
    }

    return full_out, minimal_out
    #dump_json(full_out, CFG.out_dir / "step1_confirmed.json")
    #dump_json(minimal_out, CFG.out_dir / "step1_confirmed_only.json")
    #print("Wrote:", CFG.out_dir / "step1_confirmed.json")
    #print("Wrote:", CFG.out_dir / "step1_confirmed_only.json")


#if __name__ == "__main__":
#    main()
