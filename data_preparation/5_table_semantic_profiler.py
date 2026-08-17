# -*- coding: utf-8 -*-
"""
Step 5. Table Semantic Profiler (v2)
- Task: Build a 'Table Semantic Catalog' by analyzing tables more deeply.
- Improvements: Incorporates table relationship (REFs) to better identify MASTER/HISTORY roles.
- Input: column_table_layout.csv, table_column_ref.csv
- Output: table_semantic_catalog.json
"""

import os
import json
import csv
import time
from pathlib import Path
from collections import defaultdict

class TableSemanticProfiler:
    def __init__(self, cfg):
        self.cfg = cfg
        self.api_key = " "

    def run(self):
        #print("\n[Step 5] Starting Table Semantic Profiling with Relationships...")
        
        ROOT_DIR = Path(self.cfg.data_dir).parent.parent
        layout_path = ROOT_DIR / "csv" / "column_table_layout.csv"
        ref_path = ROOT_DIR / "csv" / "table_column_ref.csv"
        
        # 1. Load basic table columns
        table_cols = defaultdict(list)
        if layout_path.exists():
            with open(layout_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t = row["table_name"].strip().lower()
                    c = row["column_name"].strip().lower()
                    table_cols[t].append(c)

        # 2. Load Table Relationships (Who references whom)
        table_refs = defaultdict(lambda: {"parents": [], "children": []})
        if ref_path.exists():
            with open(ref_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    src = row["src_table_name"].strip().lower()
                    ref = row["ref_table_name"].strip().lower()
                    if src != ref:
                        table_refs[src]["parents"].append(ref)
                        table_refs[ref]["children"].append(src)

        # 3. Use LLM to profile each table with context
        catalog = {}
        # Filter out tables starting with '_' as they are usually internal/temp tables
        unique_tables = sorted([t for t in table_cols.keys() if not t.startswith("_")])
        
        print(f" [Info] Profiling {len(unique_tables)} tables using columns & relationships...")
        
        batch_size = 8
        for i in range(0, len(unique_tables), batch_size):
            batch = unique_tables[i:i+batch_size]
            batch_data = []
            for t in batch:
                batch_data.append({
                    "table": t,
                    "columns": table_cols[t],
                    "referenced_by_children": list(set(table_refs[t]["children"])),
                    "references_parents": list(set(table_refs[t]["parents"]))
                })
            
            profiles = self.ask_llm_about_tables(batch_data)
            catalog.update(profiles)
            print(f"  Processed {min(i + batch_size, len(unique_tables))} / {len(unique_tables)} tables...")

        # 4. Save result
        out_path = Path(self.cfg.data_dir) / "table_semantic_catalog.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2, ensure_ascii=False)
        
        print(f"[Success] Table Semantic Catalog (Enriched) saved to {out_path}")

    def ask_llm_about_tables(self, batch_data):
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        
        prompt = (
            "You are a Senior Data Architect. Analyze the provided tables, their columns, and their relationships (who they reference and who references them).\n"
            "Determine the Semantic Role and Core Subject for each table.\n\n"
            "Roles:\n"
            "- MASTER: Central entities (e.g., User, Account). Usually has many children (references from others).\n"
            "- HISTORY: Stores changes over time. Usually references a MASTER.\n"
            "- TRANSACTION: High-volume event logs (e.g., Transfer history).\n"
            "- CODE: Reference/Lookup data for codes.\n"
            "- RELATION: Bridge tables for Many-to-Many relations.\n\n"
            "Output JSON object where keys are table names and values are:\n"
            "{ \"role\": \"MASTER|HISTORY|TRANSACTION|CODE|RELATION\", \"subject\": \"The primary business entity\", \"description\": \"Why this role was chosen\" }\n"
        )
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(batch_data)}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"  [Error] LLM Profiling failed: {e}")
            return {item["table"]: {"role": "UNKNOWN", "subject": "UNKNOWN", "description": str(e)} for item in batch_data}

def main(cfg):
    profiler = TableSemanticProfiler(cfg)
    profiler.run()

#if __name__ == "__main__":
#    from config import CFG
#    main(CFG)
