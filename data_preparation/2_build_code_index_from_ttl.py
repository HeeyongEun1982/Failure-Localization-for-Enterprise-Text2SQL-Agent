from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from rdflib import Graph
from rdflib.namespace import RDF

from common_text import normalize
from common_io import dump_json

def _local_name(uri: str) -> str:
    if "#" in uri: return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1]

def find_predicates_by_localname(g: Graph, local: str) -> List[Any]:
    preds = set()
    for p in g.predicates():
        try:
            if _local_name(str(p)) == local: preds.add(p)
        except Exception: continue
    return list(preds)

def first_literal(g: Graph, s, predicates: List[Any]) -> Optional[str]:
    for p in predicates:
        for o in g.objects(s, p): return str(o)
    return None

def all_literals(g: Graph, s, predicates: List[Any]) -> List[str]:
    out = []
    for p in predicates:
        for o in g.objects(s, p): out.append(str(o))
    return out

def main(cfg):
    ttl_path = cfg.ttl_path
    if not ttl_path.exists():
        raise FileNotFoundError(f"TTL not found: {ttl_path}")

    g = Graph()
    g.parse(str(ttl_path), format="turtle")

    p_physical = find_predicates_by_localname(g, "physicalName")
    p_hasCodeValue = find_predicates_by_localname(g, "hasCodeValue")

    term_subjects = set()
    for s, _, o in g.triples((None, RDF.type, None)):
        if _local_name(str(o)) == "Term": term_subjects.add(s)

    physical_to_term: Dict[str, str] = {}
    term_to_physical: Dict[str, str] = {}
    term_to_codes: Dict[str, Dict[str, Dict[str, str]]] = {}

    for s in term_subjects:
        term_id = str(s)
        physical = first_literal(g, s, p_physical)
        if physical:
            physical_to_term[physical] = term_id
            term_to_physical[term_id] = physical

        codes_raw = all_literals(g, s, p_hasCodeValue)
        cmap: Dict[str, Dict[str, str]] = {}
        for cv in codes_raw:
            m = re.match(r"^\s*([^|]+)\|(.+?)\s*$", cv)
            if not m: continue
            code, label = m.group(1).strip(), m.group(2).strip()
            nlab = normalize(label)
            if nlab: cmap[nlab] = {"code": code, "label": label}
        if cmap: term_to_codes[term_id] = cmap

    out = {
        "meta": {"sourceTtl": str(ttl_path), "termCount": len(term_subjects), "physicalMapped": len(physical_to_term), "termsWithCodes": len(term_to_codes)},
        "physicalToTerm": physical_to_term, "termToPhysical": term_to_physical, "termToCodes": term_to_codes,
    }
    dump_json(out, cfg.data_dir / "ttl_code_index.json")
    print("Wrote:", cfg.data_dir / "ttl_code_index.json")

if __name__ == "__main__":
    from config import CFG
    main(CFG)
