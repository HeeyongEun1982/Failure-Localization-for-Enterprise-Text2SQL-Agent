from __future__ import annotations

import os
from typing import Any, Dict, Optional
import psycopg2
import psycopg2.extras


def save_agent_io(
    *,
    trace_id: str,
    run_id: int,                 # <- 각 서브 에이전트가 직접 입력
    step_id: Optional[str],
    agent_name: str,
    actor_type: str,
    direction: str,              # REQUEST | RESPONSE | ARTIFACT
    payload: Dict[str, Any],
    status: str = "OK",
    error_message: Optional[str] = None,
) -> None:
    """
    단일 이벤트 저장.
    connect → insert → commit → close
    """

    request_json = None
    response_json = None
    if direction == "REQUEST":
        request_json = payload
    else:
        response_json = payload

    # DSN is managed here (per your requirement).
    # @ in password must be URL encoded as %40
    dsn = "postgresql://usr_agent_log:Kpmg1234!%40@1.1.1.1:5432/agent_log_db"
    
    print(f"[DB_LOG] Attempting to connect to {dsn.split('@')[-1]}...")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            print(f"[DB_LOG] Inserting log for trace_id={trace_id}, agent={agent_name}, direction={direction}...")
            cur.execute(
                """
                INSERT INTO agent_io_log (
                    trace_id,
                    run_id,
                    step_id,
                    agent_name,
                    actor_type,
                    direction,
                    request_json,
                    response_json,
                    status,
                    error_message
                )
                VALUES (
                    %(trace_id)s,
                    %(run_id)s,
                    %(step_id)s,
                    %(agent_name)s,
                    %(actor_type)s,
                    %(direction)s,
                    %(request_json)s,
                    %(response_json)s,
                    %(status)s,
                    %(error_message)s
                )
                """,
                {
                    "trace_id": trace_id,
                    "run_id": int(run_id),
                    "step_id": step_id,
                    "agent_name": agent_name,
                    "actor_type": actor_type,
                    "direction": direction,
                    "request_json": psycopg2.extras.Json(request_json) if request_json else None,
                    "response_json": psycopg2.extras.Json(response_json) if response_json else None,
                    "status": status,
                    "error_message": error_message,
                },
            )
            conn.commit()
            print("[DB_LOG] Successfully inserted log.")
    except Exception as e:
        print(f"[DB_LOG] Error during DB operation: {e}")
        raise
    finally:
        conn.close()
