# 4_ground_from_llm_understanding.py
# Step-4: Ground LLM-understood phrases to your CSV lexicon + TTL code lists.
#
# Inputs:
#   out/term_lexicon.json        (from 1_build_term_lexicon_from_csv.py)
#   out/ttl_code_index.json      (from 2_build_code_index_from_ttl.py)
#   out/llm_understanding.json   (from 3_llm_understand_query.py)
#
# Output:
#   out/step1_summary_llm.json

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from common_text import normalize_with_map
from common_io import load_json, dump_json
#from config import CFG


class TrieNode:
    __slots__ = ("children", "outputs")
    def __init__(self) -> None:
        self.children: Dict[str, "TrieNode"] = {}
        self.outputs: List[str] = []  # norm phrase keys that end here


class PhraseTrie:
    def __init__(self, norm_phrases: List[str]) -> None:
        self.root = TrieNode()
        for p in norm_phrases:
            self._insert(p)

    def _insert(self, s: str) -> None:
        node = self.root
        for ch in s:
            node = node.children.setdefault(ch, TrieNode())
        node.outputs.append(s)

    def find_all(self, norm_text: str) -> List[Tuple[int, int, str]]:
        matches: List[Tuple[int, int, str]] = []
        n = len(norm_text)
        for i in range(n):
            node = self.root
            j = i
            while j < n and norm_text[j] in node.children:
                node = node.children[norm_text[j]]
                j += 1
                if node.outputs:
                    for key in node.outputs:
                        matches.append((i, j, key))
        return matches


def longest_non_overlapping(matches: List[Tuple[int, int, str]], norm_len: int) -> List[Tuple[int, int, str]]:
    matches.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    occupied = [False] * (norm_len + 1)
    selected: List[Tuple[int, int, str]] = []
    for s, e, k in matches:
        if any(occupied[s:e]):
            continue
        for i in range(s, e):
            occupied[i] = True
        selected.append((s, e, k))
    selected.sort(key=lambda x: x[0])
    return selected


def spans_overlap(a: Dict[str, int], b: Dict[str, int]) -> bool:
    return not (a["end"] <= b["start"] or b["end"] <= a["start"])


def detect_terms_in_text(text: str, phrase_index: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """
    Detect term mentions inside a SHORT text chunk (LLM-provided phrase).
    Returns list of mentions with candidate physicalNames.
    """
    norm_t, idx_map = normalize_with_map(text)
    trie = PhraseTrie(list(phrase_index.keys()))
    matches = trie.find_all(norm_t)
    selected = longest_non_overlapping(matches, len(norm_t))

    mentions = []
    for s, e, nkey in selected:
        o_start = idx_map[s]
        o_end = idx_map[e - 1] + 1
        surface = text[o_start:o_end]
        physicals = phrase_index.get(nkey, [])

        mentions.append({
            "surface": surface,
            "span": {"start": o_start, "end": o_end},
            "matchKey": nkey,
            "candidates": [{"physicalName": p} for p in physicals],
            "sourceText": text,
        })
    return mentions


def main(cfg, term_lex, ttl_idx, llm_u):
    #CFG.out_dir.mkdir(parents=True, exist_ok=True)

    #term_lex = load_json(CFG.out_dir / "term_lexicon.json")
    #ttl_idx = load_json(CFG.out_dir / "ttl_code_index.json")
    #llm_u = load_json(CFG.out_dir / "llm_understanding.json")

    phrase_index: Dict[str, List[str]] = term_lex["phraseIndex"]
    rec_by_phys: Dict[str, Dict[str, Any]] = {r["physicalName"]: r for r in term_lex["records"] if r.get("physicalName")}

    physical_to_term: Dict[str, str] = ttl_idx["physicalToTerm"]
    term_to_codes: Dict[str, Dict[str, Dict[str, str]]] = ttl_idx["termToCodes"]

    parsed = llm_u["parsed"]

    # Term grounding: use LLM targets + field phrases
    term_mentions: List[Dict[str, Any]] = []
    for t in (parsed.get("targets") or []):
        term_mentions.extend(detect_terms_in_text(t, phrase_index))
    for f in (parsed.get("field_phrases") or []):
        term_mentions.extend(detect_terms_in_text(f, phrase_index))

    # De-dup
    uniq_tm = {}
    for m in term_mentions:
        k = (m["sourceText"], m["surface"], m["matchKey"])
        uniq_tm[k] = m
    term_mentions = list(uniq_tm.values())

    # Enrich with CSV hierarchy
    enriched_mentions = []
    detected_phys: List[str] = []
    term_spans_by_source: List[Dict[str, Any]] = []

    for m in term_mentions:
        cands = []
        for c in m["candidates"]:
            pn = c["physicalName"]
            if pn and pn not in detected_phys:
                detected_phys.append(pn)
            rec = rec_by_phys.get(pn, {})
            cands.append({
                "physicalName": pn,
                "originalTerm": rec.get("originalTerm"),
                "hierarchy": {
                    "entity": rec.get("entity"),
                    "aTokens": rec.get("aTokens"),
                    "classifier": rec.get("classifier"),
                }
            })
        enriched_mentions.append({
            "surface": m["surface"],
            "span": m["span"],
            "sourceText": m["sourceText"],
            "candidates": cands
        })
        term_spans_by_source.append({"sourceText": m["sourceText"], "span": m["span"]})

    # Code grounding: search ONLY in LLM conditions/value phrases
    value_search_texts: List[str] = []
    value_search_texts.extend(parsed.get("conditions_text") or [])
    value_search_texts.extend(parsed.get("value_phrases") or [])

    code_mentions: List[Dict[str, Any]] = []

    for pn in detected_phys:
        term_id = physical_to_term.get(pn)
        if not term_id:
            continue
        cmap = term_to_codes.get(term_id, {})
        if not cmap:
            continue

        for src_text in value_search_texts:
            if not src_text:
                continue
            norm_src, idx_map = normalize_with_map(src_text)

            for nlab, info in cmap.items():
                start = 0
                while True:
                    pos = norm_src.find(nlab, start)
                    if pos == -1:
                        break
                    end = pos + len(nlab)
                    o_start = idx_map[pos]
                    o_end = idx_map[end - 1] + 1
                    span = {"start": o_start, "end": o_end}

                    # avoid overlaps with column mentions in the SAME sourceText
                    overlaps = False
                    for ms in term_spans_by_source:
                        if ms["sourceText"] != src_text:
                            continue
                        if spans_overlap(span, ms["span"]):
                            overlaps = True
                            break
                    if overlaps:
                        start = pos + 1
                        continue

                    code_mentions.append({
                        "physicalName": pn,
                        "termId": term_id,
                        "code": info["code"],
                        "label": info["label"],
                        "span": span,
                        "sourceText": src_text,
                        "evidence": "TTL_CODELIST_MATCH_IN_LLM_CONDITIONS"
                    })
                    start = pos + 1

    # De-dup
    uniq_cm = {}
    for cm in code_mentions:
        k = (cm["termId"], cm["code"], cm["sourceText"], cm["span"]["start"], cm["span"]["end"])
        uniq_cm[k] = cm
    code_mentions = list(uniq_cm.values())

    # Unresolved: keep ambiguous phrases from LLM
    unresolved = [{"surface": a, "status": "UNRESOLVED_STEP1"} for a in (parsed.get("ambiguous_phrases") or [])]

    out = {
        "inputQuery": llm_u["inputQuery"],
        "llmUnderstanding": parsed,
        "termMentions": enriched_mentions,
        "codeMentions": code_mentions,
        "unresolvedMentions": unresolved,
        "diagnostics": {
            "notes": [
                "LLM-first: LLM structures the query (targets/fields/values); grounding uses CSV lexicon; code resolution uses TTL code lists.",
                "No SQL / joins / policy decisions in this step."
            ]
        }
    }

    return out

    #dump_json(out, CFG.out_dir / "step1_summary_llm.json")
    #print("Wrote:", CFG.out_dir / "step1_summary_llm.json")


#if __name__ == "__main__":
#    main()
