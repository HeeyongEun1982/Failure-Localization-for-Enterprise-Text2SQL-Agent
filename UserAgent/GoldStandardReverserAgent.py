
import json
import re
import os
import sys
import psycopg2
from typing import Any, Dict, List

class GoldStandardReverserAgent:
    """
    정답 SQL(8.gold_answer.json)을 분석하여 역방향으로 중간 결과물들을 생성하는 에이전트.
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def fetch_gold_answer(self, trace_id: str) -> Dict[str, Any]:
        dsn = "postgresql://usr_agent_log:kpmg1!@1.1.1.1:5432/agent_log_db"
        print(f"[DB] Fetching gold answer for trace_id={trace_id}...")
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT response_json FROM agent_io_log WHERE trace_id = %s AND step_id = '8'",
                    (trace_id,)
                )
                row = cur.fetchone()
                if row:
                    # row[0] is typically the dict if stored as JSONB
                    return row[0] if row[0] else {}
                else:
                    print(f"[DB] No record found for trace_id={trace_id} and step_id='8'")
                    return {}
        except Exception as e:
            print(f"[DB] Error fetching gold answer: {e}")
            return {}
        finally:
            conn.close()

    def _extract_tables(self, sql: str) -> List[str]:
        # 'FROM' 또는 'JOIN' 뒤의 테이블명 추출 (간단한 정규식 버전)
        table_matches = re.findall(r'FROM\s+([a-zA-Z0-9_]+)', sql, re.IGNORECASE)
        join_matches = re.findall(r'JOIN\s+([a-zA-Z0-9_]+)', sql, re.IGNORECASE)
        # 서브쿼리나 알리아스 처리 보완
        all_tabs = list(set([t.lower() for t in table_matches + join_matches if t.lower() not in ('select', 'from', 'where')]))
        return all_tabs

    def _extract_columns(self, sql: str) -> List[str]:
        # SELECT와 FROM 사이의 컬럼 추출
        select_part = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if not select_part: return []
        cols_raw = select_part.group(1).split(',')
        cols = []
        for c in cols_raw:
            c = c.split('as')[-1].split('AS')[-1].strip() # Alias 제거 후 실제 컬럼명 추출 시도
            c = re.sub(r'/\*.*?\*/', '', c) # 주석 제거
            c = c.split('.')[-1].strip().lower() # 테이블 접두사 제거
            if c: cols.append(c)
        return list(set(cols))

    def _db_log(self, trace_id: str, run_id: int, step_id: str, agent_name: str, direction: str, payload: Dict[str, Any], actor_type: str = "AI"):
        dsn = "postgresql://usr_agent_log:kpmg1!@1.1.1.1:5432/agent_log_db"
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                # Based on 0.db_storage.py logic
                request_json = payload if direction == "REQUEST" else None
                response_json = payload if direction != "REQUEST" else None
                
                cur.execute(
                    """
                    INSERT INTO agent_io_log (trace_id, run_id, step_id, agent_name, actor_type, direction, request_json, response_json, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'OK')
                    """,
                    (trace_id, run_id, step_id, agent_name, actor_type, direction, 
                     json.dumps(request_json) if request_json else None,
                     json.dumps(response_json) if response_json else None)
                )
                conn.commit()
                print(f"[DB_BENCHMARK] Saved Step {step_id} for {agent_name}")
        except Exception as e:
            print(f"[DB_BENCHMARK] Error saving log: {e}")
        finally:
            conn.close()

    def main(self, trace_id: str, gold_data: Dict[str, Any]):
        sql = gold_data.get("gold_answer", "")
        if not sql:
            print("No gold SQL found in input data.")
            return

        print(f"Analyzing Gold SQL: {sql[:100]}...")

        # --- Basic Parsing for Mapping ---
        tables = self._extract_tables(sql)
        columns = self._extract_columns(sql)
        root_table = tables[0] if tables else "unknown"
        
        # Simple column-to-table binding (assuming first table for all for now)
        col_bindings = {c: root_table for c in columns}

        # --- [STEP 8] Ground Truth Log ---
        self._db_log(trace_id, 8, "8", "BenchmarkLogger", "GROUND_TRUTH", {"gold_answer": sql}, actor_type="USER")

        # --- [STEP 4 -> 11] Target Columns (Format: 4_confirm_finalize.py minimal_out) ---
        column_data = {
            "confirmed": {
                "terms": [
                    {
                        "surface": c,
                        "originalTerm": c,
                        "physicalName": c,
                        "selectionRule": "GOLD_STANDARD_EXTRACT"
                    } for c in columns
                ],
                "codes": [], # Benchmarking codes from SQL is complex, leave empty or placeholder
                "unresolved": []
            }
        }
        #self._save("4.ConfirmCandidateColumn.json", column_data)
        self._db_log(trace_id, 11, "11", "BenchmarkConfirmCandidateColumnLogger", "RESPONSE", column_data)

        # --- [STEP 5 -> 10] Table Linking (Format: 5.table_linking_engine.py output) ---
        linking_data = {
            "root_anchor": root_table,
            "selected_tables": [
                {
                    "table": t, 
                    "tier": 1 if i == 0 else 2, 
                    "role": "root" if i == 0 else "join"
                } for i, t in enumerate(tables)
            ],
            "joins": [], # Simplified for now
            "column_bindings": col_bindings,
            "reasoning": ["Extracted from Gold SQL"],
            "diagnostics": {
                "missing_columns": []
            }
        }
        #self._save("5.TableLinkingEngine.json", linking_data)
        self._db_log(trace_id, 10, "10", "BenchmarkTableLinkingLogger", "RESPONSE", linking_data)

        # --- [STEP 6 -> 9] SQL Plan (Format: 6.sql_planner_agent.py output) ---
        # Try to find simple WHERE conditions
        where_match = re.search(r'WHERE\s+(.*?)(?:\s+ORDER\s+BY|\s+LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
        where_sections = []
        if where_match:
            where_text = where_match.group(1).strip()
            where_sections.append({
                "column": "unknown", # Precise mapping requires more parsing
                "operator": "EXTRACTED",
                "values": [],
                "is_negation": False,
                "matched_snippet": where_text
            })

        plan_data = {
            "where_sections": where_sections,
            "order_by_section": [],
            "limit_section": {
                "count": 1 if "LIMIT" in sql.upper() else None,
                "matched_snippet": "Extracted" if "LIMIT" in sql.upper() else ""
            },
            "dedupe_section": {"key_column": None, "policy": None, "matched_snippet": ""},
            "meta": {
                "agent": "GoldStandardReverser",
                "persona": "Benchmark_Reference",
                "timestamp": ""
            }
        }
        #self._save("6.SqlPlannerAgent.json", plan_data)
        self._db_log(trace_id, 9, "9", "BenchmarkSqlPlannerLogger", "RESPONSE", plan_data)

    def _save(self, filename: str, data: Dict[str, Any]):
        path = os.path.join(self.output_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved File: {path}")


# 실행 시 trace_id를 인자로 받음
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python GoldStandardReverserAgent.py <trace_id>")
        sys.exit(1)
    
    tid = sys.argv[1]
    out_dir = r'd:\GitHub\text2sql-generative-ai-agent-new\final\UserAgent\Interim_result'
    
    reverser = GoldStandardReverserAgent(out_dir)
    gold_data = reverser.fetch_gold_answer(tid)
    
    if gold_data:
        reverser.main(tid, gold_data)
    else:
        print("Failed to retrieve gold standard data.")


