
import json
import os
import sys
import psycopg2
from typing import Any, Dict, List

class BenchmarkCompareAgent:
    def __init__(self, data_dir: str = None):
        self.dsn = "postgresql://usr_agent_log:kpmg1!@1.1.1.1:5432/agent_log_db"
        self.data_dir = data_dir or r'd:\GitHub\text2sql-generative-ai-agent-new\final\UserAgent\Interim_result'

    def _get_db_conn(self):
        return psycopg2.connect(self.dsn)

    def fetch_logs_from_db(self, trace_id: str) -> Dict[str, Any]:
        """DB에서 실제 에이전트 결과와 정답 기반 결과를 모두 가져옴"""
        print(f"[DB] Fetching steps for comparison (trace_id: {trace_id})...")
        conn = self._get_db_conn()
        steps_data = {}
        try:
            with conn.cursor() as cur:
                # 4,5,6 (Actual) / 9,10,11 (Admin Ref)
                cur.execute(
                    "SELECT step_id, response_json FROM agent_io_log WHERE trace_id = %s AND step_id IN ('4', '5', '6', '9', '10', '11')",
                    (trace_id,)
                )
                rows = cur.fetchall()
                for sid, r_json in rows:
                    steps_data[sid] = r_json if r_json else {}
        except Exception as e:
            print(f"[DB] Error fetching logs: {e}")
        finally:
            conn.close()
        return steps_data

    def _db_log(self, trace_id: str, run_id: int, step_id: str, agent_name: str, payload: Dict[str, Any]):
        """비교 결과를 DB에 저장"""
        conn = self._get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_io_log (trace_id, run_id, step_id, agent_name, actor_type, direction, response_json, status)
                    VALUES (%s, %s, %s, %s, 'AI', 'BENCHMARK_RESULT', %s, 'OK')
                    """,
                    (trace_id, run_id, step_id, agent_name, json.dumps(payload, ensure_ascii=False))
                )
                conn.commit()
                print(f"[DB_COMPARE] Saved Step {step_id} ({agent_name}) to DB")
        except Exception as e:
            print(f"[DB_COMPARE] Error saving comparison: {e}")
        finally:
            conn.close()

    def _save_file(self, filename: str, data: Dict[str, Any]):
        """비교 결과를 로컬 파일로 저장 (BenchmarkDiffAgent 기능 통합)"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        path = os.path.join(self.data_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[FILE_COMPARE] Saved Local File: {path}")

    def compare_columns(self, actual: Dict[str, Any], admin: Dict[str, Any]) -> Dict[str, Any]:
        """Step 4 vs 11 비교"""
        actual_terms = {t.get("physicalName", "").lower() for t in actual.get("confirmed", {}).get("terms", []) if t.get("physicalName")}
        admin_terms = {t.get("physicalName", "").lower() for t in admin.get("confirmed", {}).get("terms", []) if t.get("physicalName")}
        return {
            "matched": list(actual_terms & admin_terms),
            "missing_in_actual": list(admin_terms - actual_terms),
            "extra_in_actual": list(actual_terms - admin_terms),
            "accuracy": len(actual_terms & admin_terms) / len(admin_terms) if admin_terms else 0
        }

    def compare_linking(self, actual: Dict[str, Any], admin: Dict[str, Any]) -> Dict[str, Any]:
        """Step 5 vs 10 비교"""
        a_root = actual.get("root_anchor")
        adm_root = admin.get("root_anchor")
        a_bindings = actual.get("column_bindings", {})
        adm_bindings = admin.get("column_bindings", {})
        
        mismatches = {c: {"actual": a_bindings.get(c), "admin": v} for c, v in adm_bindings.items() if a_bindings.get(c) != v}
        
        return {
            "root_match": a_root == adm_root,
            "root_details": {"actual": a_root, "admin": adm_root},
            "binding_mismatches": mismatches,
            "score": 1.0 if a_root == adm_root else 0.5
        }

    def compare_plans(self, actual: Dict[str, Any], admin: Dict[str, Any]) -> Dict[str, Any]:
        """Step 6 vs 9 비교"""
        a_where = [w.get("matched_snippet") for w in actual.get("where_sections", [])]
        adm_where = [w.get("matched_snippet") for w in admin.get("where_sections", [])]
        return {
            "where_snippets": {"actual": a_where, "admin": adm_where},
            "limit_match": actual.get("limit_section", {}).get("count") == admin.get("limit_section", {}).get("count")
        }

    def generate_final_report(self, trace_id: str, col_res: Dict, link_res: Dict, plan_res: Dict):
        """종합 분석 리포트 생성 (Step 15)"""
        print(f"[REPORT] Generating diagnostic report for {trace_id}...")
        
        report = {
            "overall_summary": {
                "column_grounding_accuracy": f"{col_res.get('accuracy', 0)*100:.1f}%",
                "table_linking_success": "YES" if link_res.get("root_match") else "NO",
                "plan_logic_match": "YES" if plan_res.get("limit_match") else "NO",
                "status": "PASS" if col_res.get("accuracy") == 1.0 and link_res.get("root_match") else "FAIL"
            },
            "error_analysis": {
                "missing_terms": col_res.get("missing_in_actual", []),
                "root_table_error": None if link_res.get("root_match") else {
                    "expected": link_res.get("root_details", {}).get("admin"),
                    "actual": link_res.get("root_details", {}).get("actual")
                },
                "binding_errors": link_res.get("binding_mismatches", {})
            },
            "recommendations": []
        }

        # 진단 및 개선 제안 (Heuristics)
        if col_res.get("missing_in_actual"):
            report["recommendations"].append(f"Grounding Failure: {len(col_res['missing_in_actual'])} terms were not found. Check if these terms exist in the CSV lexicon or if the recall logic in Step 2 needs adjustment.")
        
        if not link_res.get("root_match"):
            target_root = link_res.get("root_details", {}).get("admin")
            report["recommendations"].append(f"Linking Failure: The Search Root should have been '{target_root}'. The scoring logic in Step 5 might be over-prioritizing transaction tables over master tables.")

        if link_res.get("binding_mismatches"):
            report["recommendations"].append("Join Path Error: Some columns were bound to the wrong tables. Verify the join_graph.json or the implicit join inference logic.")

        self._db_log(trace_id, 15, "15", "BenchmarkReportAgent", report)
        return report

    def run_benchmark(self, trace_id: str):
        data = self.fetch_logs_from_db(trace_id)
        
        results = {"col": {}, "link": {}, "plan": {}}

        # 1. Compare Columns (11 vs 4 -> 14)
        if "4" in data and "11" in data:
            results["col"] = self.compare_columns(data["4"], data["11"])
            self._db_log(trace_id, 14, "14", "BenchmarkConfirmCandidateColumnCompare", results["col"])
        
        # 2. Compare Table Linking (10 vs 5 -> 13)
        if "5" in data and "10" in data:
            results["link"] = self.compare_linking(data["5"], data["10"])
            self._db_log(trace_id, 13, "13", "BenchmarkTableLinkingCompare", results["link"])
            
        # 3. Compare SQL Planning (9 vs 6 -> 12)
        if "6" in data and "9" in data:
            results["plan"] = self.compare_plans(data["6"], data["9"])
            self._db_log(trace_id, 12, "12", "BenchmarkSqlPlannerCompare", results["plan"])

        # 4. Generate Comprehensive Report (Step 15)
        if results["col"] or results["link"] or results["plan"]:
            self.generate_final_report(trace_id, results["col"], results["link"], results["plan"])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python BenchmarkCompareAgent.py <trace_id>")
        sys.exit(1)
    
    tid = sys.argv[1]
    agent = BenchmarkCompareAgent()
    agent.run_benchmark(tid)

