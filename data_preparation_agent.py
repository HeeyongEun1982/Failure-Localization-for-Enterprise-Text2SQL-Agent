import importlib
import time
import sys
import os
from config import CFG
from utils import load_db_storage, load_module_from_path

# Ensure the current directory is in the path for module loading
sys.path.append(os.path.dirname(os.path.abspath(__file__)))



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_PREP_DIR = os.path.join(BASE_DIR, "data_preparation")


def _import(module_filename: str, module_name: str):
    return load_module_from_path(module_name, os.path.join(DATA_PREP_DIR, module_filename))


def main(step_to_run: int = None):


    CFG.setTtlPath(os.path.join(DATA_DIR, "financial_ontology.ttl"))
    CFG.setStructuredTermsCsv(os.path.join(DATA_DIR, "structured_terms.csv"))
    
    # New CSVs for Table Linking
    ROOT_DIR = os.path.dirname(BASE_DIR)
    CFG.setTableLayoutCsv(os.path.join(ROOT_DIR, "csv", "column_table_layout.csv"))
    CFG.setTableRefCsv(os.path.join(ROOT_DIR, "csv", "table_column_ref.csv"))

    print("="*80)
    print(f"  [Main Agent] Starting Grounding & Schema Preparation (Step Filter: {step_to_run or 'ALL'})")
    print("="*80)
    total_start = time.time()
    

    # --- [STEP 1] Build Term Lexicon from CSV ---
    if step_to_run is None or step_to_run == 1:
        print(f"\n[STEP 1] Building Term Lexicon from CSV...")
        s1_start = time.time()
        step1 = _import("1_build_term_lexicon_from_csv.py", "build_term_lexicon_from_csv")
        step1.main(CFG)
        print(f" >> Completed in {time.time() - s1_start:.2f}s")



    # --- [STEP 2] Build Code Index from TTL ---
    if step_to_run is None or step_to_run == 2:
        print(f"\n[STEP 2] Building Code Index from TTL...")
        s2_start = time.time()
        step2 = _import("2_build_code_index_from_ttl.py", "2_build_code_index_from_ttl")
        step2.main(CFG)
        print(f" >> Completed in {time.time() - s2_start:.2f}s")


    # --- [STEP 3] Build Schema Graph for Table Linking ---
    if step_to_run is None or step_to_run == 3:
        print(f"\n[STEP 3] Building Schema Graph from Layout & Ref CSVs...")
        s3_start = time.time()
        step3 = _import("3_build_schema_graph.py", "build_schema_graph")
        step3.main(CFG)
        print(f" >> Completed in {time.time() - s3_start:.2f}s")

    # --- [STEP 4] Build Anchor Hierarchy Map ---
    if step_to_run is None or step_to_run == 4:
        print(f"\n[STEP 4] Building Anchor Hierarchy Map...")
        s4_start = time.time()
        step4 = _import("4_build_anchor_hierarchy.py", "build_anchor_hierarchy")
        step4.main(CFG)
        print(f" >> Completed in {time.time() - s4_start:.2f}s")


    # --- [STEP 5] Build Anchor Hierarchy Map ---
    if step_to_run is None or step_to_run == 5:
        print(f"\n[STEP 5] Starting Table Semantic Profiling with Relationships...")
        s5_start = time.time()
        step5 = _import("5_table_semantic_profiler.py", "table_semantic_profiler")
        step5.main(CFG)
        print(f" >> Completed in {time.time() - s5_start:.2f}s")

    print("\n" + "="*80)
    print(f"  [SUCCESS] Total Pipeline finished in {time.time() - total_start:.2f}s")
    print("="*80)

if __name__ == "__main__":
    step_arg = None
    if len(sys.argv) > 1:
        try:
            step_arg = int(sys.argv[1])
        except ValueError:
            print(f"Invalid step number: {sys.argv[1]}. Running ALL steps.")

    main(step_to_run=step_arg)

