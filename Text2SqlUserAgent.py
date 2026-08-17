import importlib
import time
import sys
import os
import uuid
from typing import Any, Dict, Optional

from config import CFG
from utils import load_db_storage, load_module_from_path
from common_io import load_json

# Ensure the current directory is in the path for module loading
sys.path.append(os.path.dirname(os.path.abspath(__file__)))



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

USER_AGENT_DIR = os.path.join(BASE_DIR, "UserAgent")
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_PREP_DIR = os.path.join(BASE_DIR, "data_preparation")


def _import(module_filename: str, module_name: str):
    return load_module_from_path(module_name, os.path.join(USER_AGENT_DIR, module_filename))



def _log(db, *, trace_id: str, run_id: int, step_id: str, agent_name: str, direction: str,
         payload: Dict[str, Any], status: str = "OK", error: Optional[str] = None, actor_type: str = "AI") -> None:
    db.save_agent_io(
        trace_id=trace_id,
        run_id=run_id,
        step_id=step_id,
        agent_name=agent_name,
        actor_type=actor_type,
        direction=direction,
        payload=payload,
        status=status,
        error_message=error,
    )


def main(user_query: str, trace_id: Optional[str] = None, gold_answer: Optional[str] = None):

    
    db = load_db_storage(BASE_DIR)

    if trace_id is None:
        trace_id = str(uuid.uuid4())
    
    run_id = 0

    CFG.setSampleQuery(user_query)
    CFG.setTtlPath(DATA_DIR + "\\" + "financial_ontology.ttl")
    CFG.setStructuredTermsCsv(DATA_DIR + "\\" + "structured_terms.csv")

    print("="*80)
    print("  [Main Agent] Starting Grounding Pipeline v2")
    print("="*80)
    total_start = time.time()
    

    # --- [STEP 1] LLM Understand Query ---
    print(f"\n[STEP 1] Understanding Query using LLM...")
    run_id += 1
    s1_start = time.time()
    step1 = _import("1_llm_understand_query.py", "llm_understand_query")
    _log(db, trace_id=trace_id, run_id=run_id, step_id="1", agent_name="llmUnderstandQueryAgent",
        direction="REQUEST", payload={"user_query": user_query})

    try:
        step1_result = step1.main(CFG)
        _log(db, trace_id=trace_id, run_id=run_id, step_id="1", agent_name="llmUnderstandQueryAgent",
            direction="RESPONSE", payload=step1_result)
    except Exception as e:
        _log(db, trace_id=trace_id, run_id=run_id, step_id="1", agent_name="llmUnderstandQueryAgent",
            direction="RESPONSE", payload={}, status="ERROR", error=str(e))
        raise




    # --- [STEP 2] ground understanding from llm result ---
    print(f"\n[STEP 2] Ground Understanding From LLM Result...")
    run_id += 1
    s2_start = time.time()
    term_lex = load_json(CFG.data_dir / "term_lexicon.json")
    ttl_idx = load_json(CFG.data_dir / "ttl_code_index.json")

    step2 = _import("2_ground_from_llm_understanding.py", "ground_from_llm_understanding")
    _log(db, trace_id=trace_id, run_id=run_id, step_id="2", agent_name="groundUnderstandingFromLlmAgent",
        direction="REQUEST", payload=step1_result)

    try:
        step2_result = step2.main(CFG, term_lex, ttl_idx, step1_result)
        _log(db, trace_id=trace_id, run_id=run_id, step_id="2", agent_name="groundUnderstandingFromLlmAgent",
            direction="RESPONSE", payload=step2_result)
    except Exception as e:
        _log(db, trace_id=trace_id, run_id=run_id, step_id="2", agent_name="groundUnderstandingFromLlmAgent",
            direction="RESPONSE", payload={}, status="ERROR", error=str(e))
        raise



    # --- [STEP 3] final select use ontology ---
    print(f"\n[STEP 3] Final Select Use Ontology...")
    run_id += 1
    s3_start = time.time()

    step3 = _import("3_final_select.py", "finalSelectUseOntology")
    _log(db, trace_id=trace_id, run_id=run_id, step_id="3", agent_name="finalSelectUseOntology",
        direction="REQUEST", payload=step1_result)

    try:
        step3_result = step3.main(CFG, step2_result)
        _log(db, trace_id=trace_id, run_id=run_id, step_id="3", agent_name="finalSelectUseOntology",
            direction="RESPONSE", payload=step3_result)
    except Exception as e:
        _log(db, trace_id=trace_id, run_id=run_id, step_id="3", agent_name="finalSelectUseOntology",
            direction="RESPONSE", payload={}, status="ERROR", error=str(e))
        raise





    # --- [STEP 4] Confirm Candidate Column ---
    print(f"\n[STEP 3] Confirm Candidate Column...")
    run_id += 1
    s4_start = time.time()

    step4 = _import("4_confirm_finalize.py", "ConfirmCandidateColumn")
    _log(db, trace_id=trace_id, run_id=run_id, step_id="4", agent_name="ConfirmCandidateColumn",
        direction="REQUEST", payload=step1_result)

    try:
        step4_full_log, step4_result = step4.main(CFG, step3_result, ttl_idx, term_lex)

        _log(db, trace_id=trace_id, run_id=run_id, step_id="4", agent_name="ConfirmCandidateColumn",
            direction="LOGGING", payload=step4_full_log)

        _log(db, trace_id=trace_id, run_id=run_id, step_id="4", agent_name="ConfirmCandidateColumn",
            direction="RESPONSE", payload=step4_result)

    except Exception as e:
        _log(db, trace_id=trace_id, run_id=run_id, step_id="4", agent_name="ConfirmCandidateColumn",
            direction="RESPONSE", payload={}, status="ERROR", error=str(e))
        raise


    ## 5번 추가할 것.. linking관련...
    # --- [STEP 5] table linking use join graph and column to table data ---
    print(f"\n[STEP 5] table linking use hierarchy and join graph...")
    run_id += 1
    s5_start = time.time()


    col2table = load_json(CFG.data_dir / "col_to_tables.json")
    jgraph = load_json(CFG.data_dir / "join_graph.json")
    hierarchy = load_json(CFG.data_dir / "anchor_hierarchy.json")
    # 주입: 테이블 세만틱 카탈로그 (Step 5.5에서 활용)
    semantic_catalog = load_json(CFG.data_dir / "table_semantic_catalog.json")
    hierarchy["semantic_catalog"] = semantic_catalog

    step5 = _import("5.table_linking_engine.py", "TableLinkingEngine")
    _log(db, trace_id=trace_id, run_id=run_id, step_id="5", agent_name="TableLinkingEngine",
        direction="REQUEST", payload=step1_result)

    try:
        step5_result = step5.main(step1_result, step4_result, col2table, jgraph, hierarchy)
        _log(db, trace_id=trace_id, run_id=run_id, step_id="5", agent_name="TableLinkingEngine",
            direction="RESPONSE", payload=step5_result)
    except Exception as e:
        _log(db, trace_id=trace_id, run_id=run_id, step_id="5", agent_name="TableLinkingEngine",
            direction="RESPONSE", payload={}, status="ERROR", error=str(e))
        raise





    # --- [STEP 8] Gold Answer Logging (for Benchmarking) ---
    if gold_answer:
        print(f"\n[STEP 8] Logging Gold Answer for benchmark...")
        run_id += 1
        _log(db, trace_id=trace_id, run_id=run_id, step_id="8", agent_name="BenchmarkLogger",
            direction="GROUND_TRUTH", payload={"gold_answer": gold_answer}, actor_type="USER")


    print("\n" + "="*80)
    print(f"  [SUCCESS][{trace_id}] Total Pipeline finished in {time.time() - total_start:.2f}s")
    print("="*80)

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python Text2SqlUserAgent.py \"your query here\" [\"gold answer here\"]")
        sys.exit(1)

    q = sys.argv[1]
    g = sys.argv[2] if len(sys.argv) > 2 else None
    result = main(user_query=q, gold_answer=g) 

