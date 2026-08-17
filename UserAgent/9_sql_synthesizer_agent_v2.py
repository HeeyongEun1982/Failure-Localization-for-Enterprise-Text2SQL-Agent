# -*- coding: utf-8 -*-
"""
Agent4 (v3.2): SQL Synthesizer (argparse X)

추가 반영
- Agent3 룰 기반 op 지원: NOT_IN, IS_NOT_NULL
- dedupe_policy 지원(EXCLUDE_DUPLICATES -> CTE + IN subquery)
"""

from __future__ import annotations
import os, json
from typing import Any, Dict, List, Optional, Tuple
from sqlglot import exp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

JOINPLAN_JSON = os.path.join(BASE_DIR, "interim_result", "7_table_join_plan.json")
CONSTRAINT_JSON = os.path.join(BASE_DIR, "interim_result", "8_constraint_plan.json")
CONSTRAINT_RESOLVED_JSON = os.path.join(BASE_DIR, "interim_result", "8.5_constraint_plan_resolved.json")
OUT_JSON = os.path.join(BASE_DIR, "interim_result", "9_sql.json")

DIALECT = "postgres"

def norm_text(x: Any) -> str:
    return "" if x is None else str(x).strip()

def parse_expr(expr_str: str) -> Tuple[Optional[str], str]:
    expr_str = norm_text(expr_str)
    if "." in expr_str:
        t, c = expr_str.split(".", 1)
        return t, c
    return None, expr_str

def col_expr(expr_str: str) -> exp.Column:
    t, c = parse_expr(expr_str)
    if t:
        return exp.Column(this=exp.Identifier(this=c), table=exp.Identifier(this=t))
    return exp.Column(this=exp.Identifier(this=c))

def build_from_join_plan(selected_plan: Dict[str, Any]) -> exp.From:
    tables = selected_plan.get("tables") or []
    join_edges = selected_plan.get("join_edges") or []
    if not tables:
        raise ValueError("selected_plan.tables is empty")

    base = exp.Table(this=exp.Identifier(this=tables[0]))
    from_ = exp.From(this=base)

    joined = {tables[0]}
    for e in join_edges:
        left = e.get("left")
        right = e.get("right")
        on_list = e.get("on") or []
        join_type = (e.get("joinType") or "INNER").upper()

        if right in joined and left not in joined:
            left, right = right, left
            swapped = [{"leftKey": kv.get("rightKey"), "rightKey": kv.get("leftKey")} for kv in on_list]
            on_list = swapped

        if right in joined:
            continue

        conds = []
        for kv in on_list:
            lk = kv.get("leftKey"); rk = kv.get("rightKey")
            if not lk or not rk:
                continue
            conds.append(
                exp.EQ(
                    this=exp.Column(this=exp.Identifier(this=lk), table=exp.Identifier(this=left)),
                    expression=exp.Column(this=exp.Identifier(this=rk), table=exp.Identifier(this=right)),
                )
            )
        on_expr = None
        if conds:
            on_expr = conds[0]
            for c in conds[1:]:
                on_expr = exp.And(this=on_expr, expression=c)

        join = exp.Join(
            this=exp.Table(this=exp.Identifier(this=right)),
            kind=join_type,
            on=on_expr,
        )
        if from_.joins:
            from_.joins.append(join)
        else:
            from_.set("joins", [join])
        joined.add(right)

    return from_

def build_select_list(selected_plan: Dict[str, Any]) -> List[exp.Expression]:
    bindings = selected_plan.get("column_bindings") or []
    out = []
    for b in bindings:
        t = norm_text(b.get("boundTable"))
        c = norm_text(b.get("column"))
        if not c:
            continue
        if t:
            out.append(exp.Column(this=exp.Identifier(this=c), table=exp.Identifier(this=t)))
        else:
            out.append(exp.Column(this=exp.Identifier(this=c)))
    return out or [exp.Star()]

def build_where(constraints: Dict[str, Any]) -> Optional[exp.Expression]:
    filters = constraints.get("filters") or []
    conds = []

    for f in filters:
        op = (f.get("op") or "").upper()
        target = norm_text(f.get("target"))
        value = f.get("value")

        if not op or not target:
            continue

        col = col_expr(target)

        if op in ("EQ", "="):
            conds.append(exp.EQ(this=col, expression=exp.Literal.string(str(value))))
        elif op in ("NEQ", "!=", "<>"):
            conds.append(exp.NEQ(this=col, expression=exp.Literal.string(str(value))))
        elif op in ("GT", ">"):
            conds.append(exp.GT(this=col, expression=exp.Literal.string(str(value))))
        elif op in ("GTE", ">="):
            conds.append(exp.GTE(this=col, expression=exp.Literal.string(str(value))))
        elif op in ("LT", "<"):
            conds.append(exp.LT(this=col, expression=exp.Literal.string(str(value))))
        elif op in ("LTE", "<="):
            conds.append(exp.LTE(this=col, expression=exp.Literal.string(str(value))))
        elif op == "LIKE":
            conds.append(exp.Like(this=col, expression=exp.Literal.string(str(value))))
        elif op == "IN" and isinstance(value, list):
            conds.append(exp.In(this=col, expressions=[exp.Literal.string(str(v)) for v in value]))
        elif op == "NOT_IN" and isinstance(value, list):
            in_expr = exp.In(this=col, expressions=[exp.Literal.string(str(v)) for v in value])
            conds.append(exp.Not(this=in_expr))
        elif op == "IS_NOT_NULL":
            conds.append(exp.Not(this=exp.Is(this=col, expression=exp.Null())))
        elif op == "IS_NULL":
            conds.append(exp.Is(this=col, expression=exp.Null()))

    if not conds:
        return None
    w = conds[0]
    for c in conds[1:]:
        w = exp.And(this=w, expression=c)
    return w

def apply_group_order_limit(q: exp.Select, constraints: Dict[str, Any]) -> exp.Select:
    group_cols = constraints.get("group_by") or []
    if group_cols:
        exprs = [col_expr(gc) for gc in group_cols]
        q.set("group", exp.Group(expressions=exprs))

    order_by = constraints.get("order_by") or []
    if order_by:
        orders = []
        for ob in order_by:
            expr = norm_text(ob.get("expr"))
            if not expr:
                continue
            direction = (ob.get("dir") or "ASC").upper()
            orders.append(exp.Ordered(this=col_expr(expr), desc=(direction == "DESC")))
        if orders:
            q.set("order", exp.Order(expressions=orders))

    lim = constraints.get("limit")
    if isinstance(lim, int) and lim > 0:
        q.set("limit", exp.Limit(this=exp.Literal.number(lim)))

    return q

def apply_dedupe_cte(q: exp.Select, constraints: Dict[str, Any], selected_plan: Dict[str, Any]) -> exp.Select:
    dedupe = constraints.get("dedupe_policy")
    if not isinstance(dedupe, dict):
        return q
    if (dedupe.get("type") or "").upper() not in ("EXCLUDE_NON_UNIQUE_KEYS", "EXCLUDE_DUPLICATES"):
        return q

    key_expr = norm_text(dedupe.get("key"))
    if not key_expr:
        return q

    # Determine table for key; if not provided, try infer from selected_plan.tables[0]
    t, c = parse_expr(key_expr)
    if not t:
        tables = selected_plan.get("tables") or []
        t = tables[0] if tables else None
    if not t or not c:
        return q

    key_col = exp.Column(this=exp.Identifier(this=c), table=exp.Identifier(this=t))
    key_col_naked = exp.Column(this=exp.Identifier(this=c))

    # uniq CTE: SELECT key FROM t GROUP BY key HAVING COUNT(*) = 1
    uniq_select = exp.Select(expressions=[key_col_naked]).from_(exp.Table(this=exp.Identifier(this=t)))
    uniq_select.set("group", exp.Group(expressions=[key_col_naked]))
    uniq_select.set("having", exp.Having(this=exp.EQ(this=exp.Count(this=exp.Star()), expression=exp.Literal.number(1))))

    cte = exp.CTE(this=uniq_select, alias=exp.TableAlias(this=exp.Identifier(this="uniq")))
    with_ = exp.With(expressions=[cte])

    # Add WHERE key IN (SELECT key FROM uniq)
    in_sub = exp.Select(expressions=[key_col_naked]).from_(exp.Table(this=exp.Identifier(this="uniq")))
    in_cond = exp.In(this=key_col, expressions=[in_sub])

    existing_where = q.args.get("where")
    if existing_where and isinstance(existing_where, exp.Where):
        new_where = exp.And(this=existing_where.this, expression=in_cond)
        q.set("where", exp.Where(this=new_where))
    else:
        q.set("where", exp.Where(this=in_cond))

    q.set("with", with_)
    return q

def run():
    with open(JOINPLAN_JSON, "r", encoding="utf-8") as f:
        jp = json.load(f)
    selected_plan = (jp.get("join_planning") or {}).get("selected_plan") or {}
    if not selected_plan:
        raise ValueError("Missing join_planning.selected_plan in 7_table_join_plan.json")

    cp_path = CONSTRAINT_RESOLVED_JSON if os.path.exists(CONSTRAINT_RESOLVED_JSON) else CONSTRAINT_JSON
    with open(cp_path, "r", encoding="utf-8") as f:
        cp = json.load(f)
    cp["_trace_constraint_source"] = os.path.basename(cp_path)

    from_ = build_from_join_plan(selected_plan)
    select_list = build_select_list(selected_plan)
    where_expr = build_where(cp)

    q = exp.Select(expressions=select_list)
    q.set("from", from_)

    if where_expr is not None:
        q.set("where", exp.Where(this=where_expr))

    q = apply_group_order_limit(q, cp)
    q = apply_dedupe_cte(q, cp, selected_plan)

    sql = q.sql(dialect=DIALECT)

    out = {
        "sql": sql,
        "dialect": DIALECT,
        "trace": {
            "tables": selected_plan.get("tables") or [],
            "n_joins": len(selected_plan.get("join_edges") or []),
            "n_select_cols": len(select_list),
            "dedupe_applied": bool((cp.get("dedupe_policy") or {}).get("type")),
        },
        "ast": {"pretty": q.to_s()}
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] Agent4 wrote: {OUT_JSON}")
    print(sql)

if __name__ == "__main__":
    run()
