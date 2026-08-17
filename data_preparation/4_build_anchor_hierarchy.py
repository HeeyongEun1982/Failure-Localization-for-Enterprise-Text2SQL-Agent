"""
Step 4. Logical Anchor-Master Hierarchy Builder.
- Focus strictly on:
  1. Table Tiering (Master/Sub/History)
  2. Logical Concept (Anchor) -> Table Mapping
  3. Physical Attribute -> Owner Table Mapping (Master Priority)
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from collections import defaultdict
import rdflib

def dump_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def main(cfg):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    ROOT_DIR = Path(cfg.data_dir).parent.parent
    layout_path = ROOT_DIR / "csv" / "column_table_layout.csv"
    ref_path = ROOT_DIR / "csv" / "table_column_ref.csv"
    terms_path = cfg.structured_terms_csv
    ttl_path = cfg.ttl_path

    # 1. 중앙성 분석 (참조 횟수)
    table_to_children = defaultdict(set)
    if ref_path.exists():
        with ref_path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src, ref = row["src_table_name"].strip().lower(), row["ref_table_name"].strip().lower()
                if src != ref: table_to_children[ref].add(src)
    table_centrality = {t: len(children) for t, children in table_to_children.items()}

    # 2. TTL 로드
    print("Parsing TTL entities...")
    g = rdflib.Graph()
    g.parse(str(ttl_path), format="turtle")
    entities = {str(o).strip().lower(): str(o).strip() for s, p, o in g.triples((None, rdflib.RDFS.label, None))}

    # 3. 테이블 위계 분류 (bc0001, ac0101 등 핵심 보장)
    print("Classifying Table Tiers (1: Master, 2: Sub, 3: History)...")
    all_tables = set()
    table_to_cols = defaultdict(list)
    table_schemas = {}
    with layout_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c, t, s = row["column_name"].strip().lower(), row["table_name"].strip().lower(), row["table_schema"].strip().lower()
            all_tables.add(t)
            table_to_cols[t].append(c)
            table_schemas[t] = s

    table_tiers = {}
    MUST_MASTERS = {"ac0101", "bc0001", "ac0204", "fp3003", "ad0101"}
    for t in all_tables:
        centrality = table_centrality.get(t, 0)
        is_sub_hist = any(p in t for p in ["_h", "_hist", "_tr", "_log", "_his"])
        
        if is_sub_hist: table_tiers[t] = 3
        elif t in MUST_MASTERS or (centrality >= 5 and not t.startswith("_")): table_tiers[t] = 1
        else: table_tiers[t] = 2

    # 4. 속성 주인 결정 (Master First)
    print("Resolving Attribute Ownership...")
    attr_owner_table = {}
    col_to_tabs = defaultdict(list)
    for t, cols in table_to_cols.items():
        for c in cols: col_to_tabs[c].append(t)
    
    for col, tabs in col_to_tabs.items():
        # 순위: 티어(1이 우선) > 이름순(언더바 제외) > 중앙성
        best = sorted(tabs, key=lambda tx: (table_tiers.get(tx, 2), tx.startswith("_"), -table_centrality.get(tx, 0)))[0]
        attr_owner_table[col] = best

    # 5. 엔티티별 앵커 선정
    entity_to_anchor = {}
    with terms_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            logical, physical = row.get("Original_Term", "").strip().lower(), row.get("Physical_Name", "").strip().lower()
            if logical in entities:
                owner_t = attr_owner_table.get(physical)
                if owner_t:
                    if logical not in entity_to_anchor or table_tiers.get(owner_t, 2) < table_tiers.get(entity_to_anchor[logical], 2):
                        entity_to_anchor[logical] = owner_t

    hierarchy = {
        "meta": {"anchor_count": len(entity_to_anchor), "table_count": len(all_tables)},
        "anchors": entity_to_anchor,
        "attributes": attr_owner_table,
        "table_tiers": table_tiers
    }

    dump_json(hierarchy, cfg.data_dir / "anchor_hierarchy.json")
    print(f"\n[Success] Clean Hierarchy with {len(entity_to_anchor)} anchors built.")

if __name__ == "__main__":
    from config import CFG
    main(CFG)
