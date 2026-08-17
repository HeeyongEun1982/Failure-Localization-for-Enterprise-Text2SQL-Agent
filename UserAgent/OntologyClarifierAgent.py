import os, json, uuid, re
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from datetime import datetime

# ---------- Fixed Schemas ----------

SLOT_KEYS = ["fee_kind", "product_or_service", "channel", "currency", "time_window", "condition"]

@dataclass
class Candidate:
    term_id: str
    label: str
    entity: str
    score: float
    evidence: Dict[str, Any]

@dataclass
class Decision:
    selected_term_id: Optional[str]
    reason: str
    missing_slots: List[str]
    next_question: Optional[str]

# ---------- Utilities ----------

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def write_json(path: str, obj: Any):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---------- Minimal TTL Index (MVP) ----------
# MVP에서는 TTL을 "정교하게" 파싱하지 말고,
# 1) 미리 term_id / label / entity 정도만 추출해서 index.json으로 만들어두거나
# 2) 간단한 정규식으로 label/altLabel만 긁는 수준으로 시작하세요.
#
# 여기서는 "이미 index가 있다"는 가정으로 간단한 로더만 제공합니다.
# index item example:
# {"term_id":"meta:Fee_Withdrawal","label":"출금수수료","entity":"meta:Entity_수수료","alt_labels":["현금인출수수료"]}

def load_ontology_index(index_path: str) -> List[Dict[str, Any]]:
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)

def simple_tokenize(text: str) -> List[str]:
    # Korean + alnum tokens
    return re.findall(r"[가-힣]+|[A-Za-z0-9_]+", text.lower())

def score_match(query_tokens: List[str], item: Dict[str, Any]) -> Candidate:
    label = (item.get("label") or "").lower()
    alt = [a.lower() for a in item.get("alt_labels", [])]
    matched = []
    for t in query_tokens:
        if t and (t in label or any(t in a for a in alt)):
            matched.append(t)
    # Very simple score: coverage + small bias for exact token count
    score = 0.0
    if query_tokens:
        score = min(1.0, len(set(matched)) / max(1, len(set(query_tokens))))
    evidence = {
        "matched_fields": ["label/alt_labels"] if matched else [],
        "matched_tokens": sorted(set(matched))
    }
    return Candidate(
        term_id=item["term_id"],
        label=item.get("label", ""),
        entity=item.get("entity", ""),
        score=score,
        evidence=evidence
    )

# ---------- Step A: Intent ----------
def classify_intent(user_query: str) -> Dict[str, Any]:
    q = user_query.strip()
    # MVP rule-based: "수수료" mention => FeeInquiry
    intent = "FeeInquiry" if ("수수료" in q) else "Unknown"
    return {"intent": intent, "confidence": 0.6 if intent == "FeeInquiry" else 0.2}

# ---------- Step B: Slot Fill (MVP: conservative, mostly null) ----------
def fill_slots(user_query: str, intent: str) -> Dict[str, Any]:
    slots = {k: None for k in SLOT_KEYS}
    q = user_query

    # minimal heuristics (MVP): ONLY obvious ones
    if "원화" in q: slots["currency"] = "KRW"
    if "달러" in q or "usd" in q.lower(): slots["currency"] = "USD"
    if "한달" in q or "1개월" in q: slots["time_window"] = "P1M"
    if "2일전" in q: slots["time_window"] = "P2D_BEFORE"

    # fee_kind hints (VERY conservative)
    for kind, kw in [
        ("transfer", "이체"),
        ("withdrawal", "출금"),
        ("deposit", "입금"),
        ("trading", "매매"),
        ("fx", "환전"),
    ]:
        if kw in q:
            slots["fee_kind"] = kind
            break

    return {"slots": slots, "notes": "MVP conservative slot fill (null allowed)"}

# ---------- Step C: Candidate Retrieval ----------
def retrieve_candidates(user_query: str, ontology_index: List[Dict[str, Any]], entity_filter: str = "meta:Entity_수수료") -> Dict[str, Any]:
    tokens = simple_tokenize(user_query)
    cands: List[Candidate] = []
    for item in ontology_index:
        if entity_filter and item.get("entity") != entity_filter:
            continue
        c = score_match(tokens, item)
        if c.score > 0:
            cands.append(c)

    cands.sort(key=lambda x: x.score, reverse=True)
    top = cands[:10]
    return {
        "candidates": [asdict(c) for c in top],
        "stats": {"token_count": len(tokens), "candidate_count": len(cands), "returned": len(top)}
    }

# ---------- Step D: Decision Gate ----------
def decide(intent: str, slots: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if intent != "FeeInquiry":
        return asdict(Decision(
            selected_term_id=None,
            reason="intent_not_supported",
            missing_slots=[],
            next_question="어떤 정보를 원하시는지 조금만 더 구체적으로 말해줄 수 있을까요?"
        ))

    missing = []
    # fee_kind is the biggest disambiguator in fee questions
    if not slots.get("fee_kind"):
        missing.append("fee_kind")

    # If missing critical slot => ASK
    if missing:
        return asdict(Decision(
            selected_term_id=None,
            reason="missing_critical_slots",
            missing_slots=missing,
            next_question="어떤 수수료인지요? (예: 이체/출금/입금/매매/환전)"
        ))

    # If we have fee_kind but candidate list is weak => ASK
    if not candidates:
        return asdict(Decision(
            selected_term_id=None,
            reason="no_candidates",
            missing_slots=[],
            next_question="어느 상품/서비스의 수수료인지요? (예: 특정 계좌/카드/증권/환전 서비스)"
        ))

    # FINAL only when top1 is clearly better than top2
    top1 = candidates[0]
    top2 = candidates[1] if len(candidates) > 1 else None
    gap_ok = (top2 is None) or ((top1["score"] - top2["score"]) >= 0.25)
    score_ok = top1["score"] >= 0.55

    if score_ok and gap_ok:
        return asdict(Decision(
            selected_term_id=top1["term_id"],
            reason="confident_top1",
            missing_slots=[],
            next_question=None
        ))

    return asdict(Decision(
        selected_term_id=None,
        reason="ambiguous_candidates",
        missing_slots=[],
        next_question="수수료 종류/상품/채널 중 어떤 것을 기준으로 확인할까요? (예: 이체 수수료, MTS 수수료 등)"
    ))

# ---------- Orchestrator Agent ----------
class OntologyClarifierMVP:
    def __init__(self, ontology_index_path: str, artifact_root: str = "artifacts"):
        self.ontology = load_ontology_index(ontology_index_path)
        self.artifact_root = artifact_root

    def run(self, user_query: str) -> Dict[str, Any]:
        trace_id = str(uuid.uuid4())
        base_dir = os.path.join(self.artifact_root, trace_id)
        ensure_dir(base_dir)

        # Step A
        A = classify_intent(user_query)
        write_json(os.path.join(base_dir, "A_intent.json"), {"ts": now_iso(), **A})

        # Step B
        B = fill_slots(user_query, A["intent"])
        write_json(os.path.join(base_dir, "B_slots.json"), {"ts": now_iso(), **B})

        # Step C
        C = retrieve_candidates(user_query, self.ontology)
        write_json(os.path.join(base_dir, "C_candidates.json"), {"ts": now_iso(), **C})

        # Step D
        D = decide(A["intent"], B["slots"], C["candidates"])
        write_json(os.path.join(base_dir, "D_decision.json"), {"ts": now_iso(), **D})

        status = "FINAL" if D["selected_term_id"] else "ASK"
        canonical = user_query.strip()
        if status == "FINAL":
            canonical = f"{user_query.strip()} (term={D['selected_term_id']})"

        final_obj = {
            "trace_id": trace_id,
            "status": status,
            "user_query": user_query,
            "canonical_query": canonical,
            "slots": B["slots"],
            "candidates": C["candidates"],
            "decision": D,
            "artifacts": [
                {"step": "A_intent", "path": os.path.join(base_dir, "A_intent.json")},
                {"step": "B_slots", "path": os.path.join(base_dir, "B_slots.json")},
                {"step": "C_candidates", "path": os.path.join(base_dir, "C_candidates.json")},
                {"step": "D_decision", "path": os.path.join(base_dir, "D_decision.json")},
            ]
        }
        write_json(os.path.join(base_dir, "FINAL.json"), {"ts": now_iso(), **final_obj})
        return final_obj