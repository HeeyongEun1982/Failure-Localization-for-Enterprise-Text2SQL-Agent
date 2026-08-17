"""
Step 3. Build Schema Graph with Explicit Anchor-Master Hierarchy.
Defines Top-level Anchors (Entities) and maps relationships.
"""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Dict, List, Any
from common_io import dump_json

def main(cfg):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    layout_path = cfg.table_layout_csv
    ref_path = cfg.table_ref_csv

    # 1. 최상위 Anchor Master 정의 (비즈니스 핵심 엔티티)
    ANCHOR_MASTERS = {
        "ac0101": "Account_Master",
        "ac0204": "Client_Master", # CIF 마스터
        "bc0001": "User_Master",
        "ad0101": "Employee_Master",
        "bc1011": "Contract_Master"
    }

    tables = {}
    
    # 2. 기본 테이블 및 컬럼 정보 로드
    print(f"Loading table layout from {layout_path.name}...")
    with layout_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tbl = row["table_name"].strip().lower()
            col = row["column_name"].strip().lower()
            schema = row["table_schema"].strip().lower()

            if tbl not in tables:
                # 위계 판별: Anchor > Sub-Master > Objects
                is_anchor = tbl in ANCHOR_MASTERS
                is_sub = (not is_anchor) and tbl.endswith("0101") # 일반 업무 마스터
                
                tables[tbl] = {
                    "table_name": tbl,
                    "schema": schema,
                    "is_anchor": is_anchor,
                    "is_master": is_anchor or is_sub,
                    "entity_type": "ANCHOR" if is_anchor else ("MASTER" if is_sub else "OBJECT"),
                    "columns": []
                }
            tables[tbl]["columns"].append(col)

    # 3. JOIN 관계 및 인접 행렬 구축
    print(f"Loading relationships from {ref_path.name}...")
    col_to_tables = {}
    join_graph = {}
    
    with ref_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            s_tbl, s_col = row["src_table_name"].strip().lower(), row["src_column_name"].strip().lower()
            r_tbl, r_col = row["ref_table_name"].strip().lower(), row["ref_column_name"].strip().lower()

            if s_tbl not in join_graph: join_graph[s_tbl] = []
            join_graph[s_tbl].append({"to": r_tbl, "from_col": s_col, "to_col": r_col})

    # 4. col_to_tables 데이터 생성 (위계 정보 포함)
    for t_name, info in tables.items():
        for col in info["columns"]:
            if col not in col_to_tables: col_to_tables[col] = []
            col_to_tables[col].append({
                "table": t_name,
                "schema": info["schema"],
                "type": info["entity_type"],
                "priority": 100 if info["is_anchor"] else (50 if info["is_master"] else 1)
            })

    # 파일 저장
    dump_json(col_to_tables, cfg.data_dir / "col_to_tables.json")
    dump_json(join_graph, cfg.data_dir / "join_graph.json")
    dump_json({"tables": tables, "anchors": ANCHOR_MASTERS}, cfg.data_dir / "schema_graph.json")

    print(f"Generated hierarchy-aware data in {cfg.data_dir}")

if __name__ == "__main__":
    from config import CFG
    main(CFG)
