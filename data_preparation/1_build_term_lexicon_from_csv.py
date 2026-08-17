"""
Step 1. Build TERM (column) lexicon from structured CSV.

Hardcoding policy:
- NO domain keyword lists.
- Only CSV fields are used to generate matchable phrases.

Output:
- out/term_lexicon.json
"""
from __future__ import annotations
import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from common_text import normalize
from common_io import dump_json
#from config import CFG

# ---- Adapt these column names if your CSV differs ----
# We keep these names minimal and generic; if missing, we'll best-effort detect.
POSSIBLE_COLS = [
    "Physical_Name", "Original_Term", "Entity", "A1", "A2", "A3", "A4", "A5", "Classifier"
]

def _detect_columns(header: List[str]) -> Dict[str, str]:
    """
    Map expected logical names to actual CSV header names.
    """
    hset = {h.strip(): h.strip() for h in header}
    mapping = {}
    for col in POSSIBLE_COLS:
        if col in hset:
            mapping[col] = col
    return mapping

def _safe_get(row: Dict[str, str], key: str, mapping: Dict[str, str]) -> str:
    actual = mapping.get(key)
    if not actual:
        return ""
    return (row.get(actual) or "").strip()

def _join_tokens(tokens: List[str]) -> str:
    tokens = [t.strip() for t in tokens if t and t.strip()]
    return " ".join(tokens).strip()

def _generate_phrases(physical: str, original_term: str, entity: str, a_tokens: List[str], classifier: str) -> List[str]:
    """
    Generate phrases that users might write, using ONLY the structured tokens.
    Examples generated:
      - Original_Term
      - Entity + A... + Classifier
      - concatenated version without spaces (handled via normalize)
      - Physical_Name (for power users)
    """
    phrases = []
    if original_term:
        phrases.append(original_term)
    joined = _join_tokens([entity] + a_tokens + [classifier])
    if joined:
        phrases.append(joined)
    # sometimes users omit classifier
    joined2 = _join_tokens([entity] + a_tokens)
    if joined2 and joined2 != joined:
        phrases.append(joined2)
    if physical:
        phrases.append(physical)
    # de-dupe preserving order
    seen = set()
    out = []
    for p in phrases:
        np = normalize(p)
        if not np:
            continue
        if np in seen:
            continue
        seen.add(np)
        out.append(p)
    return out

def main(cfg):
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = cfg.structured_terms_csv
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        mapping = _detect_columns([h.strip() for h in header])

        required = ["Physical_Name", "Original_Term"]
        missing = [c for c in required if c not in mapping]
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}. Found: {header}")

        records = []
        phrase_index: Dict[str, List[str]] = {}  # norm_phrase -> [physical_name,...]

        for row in reader:
            physical = _safe_get(row, "Physical_Name", mapping)
            original_term = _safe_get(row, "Original_Term", mapping)
            entity = _safe_get(row, "Entity", mapping)
            classifier = _safe_get(row, "Classifier", mapping)

            a_tokens = []
            for ak in ["A1","A2","A3","A4","A5"]:
                a_tokens.append(_safe_get(row, ak, mapping))

            phrases = _generate_phrases(physical, original_term, entity, a_tokens, classifier)

            rec = {
                "physicalName": physical,
                "originalTerm": original_term,
                "entity": entity,
                "aTokens": [t for t in a_tokens if t.strip()],
                "classifier": classifier,
                "phrases": phrases,
            }
            records.append(rec)

            for p in phrases:
                np = normalize(p)
                phrase_index.setdefault(np, [])
                if physical and physical not in phrase_index[np]:
                    phrase_index[np].append(physical)

        out = {
            "meta": {
                "sourceCsv": str(csv_path),
                "recordCount": len(records),
                "uniquePhraseKeys": len(phrase_index),
            },
            "records": records,
            "phraseIndex": phrase_index,
        }

    dump_json(out, cfg.data_dir / "term_lexicon.json")
    print("Wrote:", cfg.data_dir / "term_lexicon.json")

#if __name__ == "__main__":
#    main()
