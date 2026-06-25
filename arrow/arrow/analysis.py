"""Structured task packets + validation (optional Ollama); deterministic hints first."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arrow.ollama_client import analysis_model_name, extract_json_object, ollama_chat


def _resolve_analysis_model(explicit: Optional[str]) -> str:
    m = (explicit or analysis_model_name()).strip()
    if not m:
        raise ValueError(
            "No Ollama model configured. Set ARROW_ANALYSIS_MODEL to a model you have pulled "
            "(e.g. qwen2.5:7b-instruct), then retry why / summarize."
        )
    return m


def _coerce_str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


class ExplainRankResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fit_score_explanation: List[str] = Field(default_factory=list)
    strong_signals: List[str] = Field(default_factory=list)
    weak_signals: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    confidence: str = "medium"
    recommended_next_read: str = ""

    @field_validator("fit_score_explanation", "strong_signals", "weak_signals", "risks", "missing_fields", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> List[str]:
        return _coerce_str_list(v)

    @field_validator("recommended_next_read", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: Any) -> str:
        s = str(v or "medium").strip().lower()
        return s if s in ("high", "medium", "low") else "medium"


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", (s or "").lower()))


def _digits_naics(code: str) -> str:
    return re.sub(r"\D", "", (code or "").strip())


def _naics_sector2(digits: str) -> str:
    d = _digits_naics(digits)
    return d[:2] if len(d) >= 2 else ""


# Coarse NAICS 2-digit sectors often treated as one “ecosystem” for capture (not regulatory truth).
# Used only when there is no exact or lineage NAICS match — partial alignment, not a NAICS “match”.
_MOBILITY_ECOSYSTEM_2D = frozenset({"32", "33", "48", "53"})


def notice_naics_code(notice: Dict[str, Any]) -> str:
    n = str(notice.get("naicsCode") or "").strip()
    if n:
        return n
    cc = notice.get("csvColumns")
    if isinstance(cc, dict):
        v = cc.get("NaicsCode") or cc.get("NAICS Code") or cc.get("naicsCode")
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def notice_description_text(notice: Dict[str, Any], *, max_len: int = 8000) -> str:
    d = str(notice.get("description") or "").strip()
    if len(d) >= 80:
        return d[:max_len]
    cc = notice.get("csvColumns")
    if isinstance(cc, dict):
        for k in ("Description", "description", "DESCRIPTION"):
            v = cc.get(k)
            if v is not None and str(v).strip():
                d = str(v).strip()
                break
    return d[:max_len]


def notice_set_aside_label(notice: Dict[str, Any]) -> str:
    for k in ("typeOfSetAsideDescription", "typeOfSetAside"):
        v = str(notice.get(k) or "").strip()
        if v:
            return v
    cc = notice.get("csvColumns")
    if isinstance(cc, dict):
        v = cc.get("SetASide") or cc.get("SetASideDescription")
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _naics_relation_one(target_digits: str, notice_digits: str) -> str:
    """How one profile target relates to notice NAICS (digit-only strings)."""
    t, n = target_digits, notice_digits
    if not t or not n:
        return "none"
    if t == n:
        return "exact"
    longer, shorter = (t, n) if len(t) >= len(n) else (n, t)
    if len(shorter) >= 5 and longer.startswith(shorter):
        return "lineage"
    if len(t) >= 4 and len(n) >= 4 and t[:4] == n[:4]:
        return "sector4"
    return "none"


def naics_block_for_targets(targets: List[str], notice_code: str) -> Dict[str, Any]:
    n = _digits_naics(notice_code)
    tnorm = [_digits_naics(x) for x in targets if _digits_naics(x)]
    order = {"none": 0, "sector4": 1, "lineage": 2, "exact": 3}
    best = "none"
    matched: Optional[str] = None
    for t in tnorm:
        r = _naics_relation_one(t, n)
        if order[r] > order[best]:
            best = r
            matched = t
    unrelated = [t for t in tnorm if _naics_relation_one(t, n) == "none"]
    exact = best == "exact"
    lineage = best == "lineage"
    sector4 = best == "sector4"
    n2 = _naics_sector2(n)
    mobility_notice = n2 in _MOBILITY_ECOSYSTEM_2D
    mobility_any_target = any(_naics_sector2(t) in _MOBILITY_ECOSYSTEM_2D for t in tnorm)
    # No exact/lineage/sector4 win, but e.g. 33xxxx manufacturing vs 53xxxx rental — same coarse mobility stack.
    domain_adjacent = bool(n and tnorm and best == "none" and mobility_notice and mobility_any_target)
    domain_cluster = "vehicle_mobility_ecosystem" if domain_adjacent else None

    if exact:
        bonus = 24
    elif lineage:
        bonus = 17
    elif best == "sector4":
        bonus = 12
    elif domain_adjacent:
        bonus = 10
    else:
        bonus = 0

    # Any positive NAICS-side signal for narrative.
    match_for_score = exact or lineage or domain_adjacent or (best == "sector4")
    return {
        "notice_naics_normalized": n,
        "profile_target_naics_normalized": tnorm,
        "best_naics_relation": best,
        "naics_matched_target": matched,
        "naics_exact_match": exact,
        "naics_lineage_match": lineage,
        "naics_same_4_digit_sector": sector4 or lineage or exact,
        "naics_domain_adjacent": domain_adjacent,
        "naics_domain_cluster": domain_cluster,
        "naics_match_for_score": match_for_score,
        "naics_bonus_points": bonus,
        "naics_profile_targets_unrelated_to_notice": unrelated,
    }


# Raw = overlap (0–100) + NAICS tier bonus (0–24 max). Denominator tuned so strong rows reach high 0–1 without maxing trivially.
FIT_SCORE_RAW_MAX = 100.0


def fit_score_unit(overlap: int, naics_bonus: int) -> float:
    """Linear map overlap + NAICS bonus to [0.0, 1.0], capped at raw >= FIT_SCORE_RAW_MAX → 1.0."""
    raw = float(overlap + naics_bonus)
    t = min(1.0, raw / FIT_SCORE_RAW_MAX)
    return round(max(0.0, min(1.0, t)), 4)


def naive_deterministic_fit(profile: Dict[str, Any], notice: Dict[str, Any]) -> Dict[str, Any]:
    mission = " ".join(
        [
            str(profile.get("mission") or ""),
            str(profile.get("notes") or ""),
            " ".join(profile.get("target_naics") or []),
        ]
    )
    title = str(notice.get("title") or "").strip()
    cc = notice.get("csvColumns")
    if isinstance(cc, dict) and not title:
        title = str(cc.get("Title") or cc.get("title") or "").strip() or title
    desc = notice_description_text(notice, max_len=4000)
    naics_raw = notice_naics_code(notice)
    agency = str(notice.get("fullParentPathName") or "").strip()
    if not agency and isinstance(cc, dict):
        agency = str(cc.get("Department/Ind.Agency") or cc.get("Sub-Tier") or "").strip() or agency
    blob = f"{title} {desc} {naics_raw} {agency}"
    m = _tokens(mission)
    b = _tokens(blob)
    tgt = [str(x).strip() for x in (profile.get("target_naics") or []) if str(x).strip()]
    naics_info = naics_block_for_targets(tgt, naics_raw)
    naics_bonus = int(naics_info.get("naics_bonus_points") or 0)

    set_side = notice_set_aside_label(notice)
    low = set_side.lower()
    open_competition = not set_side or "none" in low or "no set aside" in low

    bt = (str(notice.get("baseType") or "") + " " + str(notice.get("type") or "")).lower()
    if isinstance(cc, dict):
        bt += " " + str(cc.get("BaseType") or "") + " " + str(cc.get("Type") or "")
        bt = bt.lower()
    is_sol = any(
        k in bt
        for k in (
            "solicitation",
            "synopsis",
            "sources sought",
            "special notice",
            "combined synopsis",
        )
    )

    if not m:
        sig = {
            **naics_info,
            "keyword_overlap_score": 0,
            "set_aside_notice": set_side or None,
            "set_aside_open_competition": open_competition,
            "is_solicitation_like": is_sol,
            "analysis_hints": [
                "Profile mission/notes empty — still use NAICS flags; do not invent company fit.",
            ],
        }
        total = 0.0
        sig["fit_score_0_1"] = total
        return {
            "total": total,
            "components": {"keyword_overlap": 0, "naics_bonus": naics_bonus, "raw_points": naics_bonus},
            "deterministic_signals": sig,
            "note": "empty mission in profile; fit score 0 until mission/notes/NAICS are set",
        }

    inter = len(m & b)
    union = len(m | b) or 1
    # Boosted vs pure Jaccard so keyword overlap contributes more before the 100 cap.
    overlap = int(round(min(100.0, 122.0 * inter / float(union))))
    raw_points = overlap + naics_bonus
    total = fit_score_unit(overlap, naics_bonus)
    sig = {
        **naics_info,
        "keyword_overlap_score": overlap,
        "set_aside_notice": set_side or None,
        "set_aside_open_competition": open_competition,
        "is_solicitation_like": is_sol,
    }
    hints: List[str] = []
    if tgt and naics_info.get("notice_naics_normalized"):
        if naics_info.get("naics_exact_match") or naics_info.get("naics_lineage_match"):
            unr = naics_info.get("naics_profile_targets_unrelated_to_notice") or []
            if len(unr) >= 1:
                hints.append(
                    "NAICS: profile lists targets with no direct NAICS relationship to this notice — "
                    "state partial vs whole-profile fit (e.g. one aligned code vs other unrelated targets)."
                )
        elif naics_info.get("naics_domain_adjacent"):
            hints.append(
                "NAICS: no exact or lineage match, but `naics_domain_adjacent` is true — same coarse industry "
                "ecosystem (see `naics_domain_cluster`). Describe as partial NAICS alignment, not unrelated "
                "industries. High keyword/title domain overlap can outweigh lack of exact NAICS unless codes are "
                "clearly unrelated (no domain flag)."
            )
        else:
            hints.append(
                "NAICS: no exact, lineage, or domain-ecosystem link — treat as weak NAICS alignment; "
                "do not invent cross-industry bridges."
            )
    elif tgt and not naics_info.get("notice_naics_normalized"):
        hints.append("NAICS: missing on notice — list under missing_fields.")
    if open_competition:
        hints.append("Set-aside: open / none — cite competitive exposure under risks if relevant.")
    if len(desc) < 200:
        hints.append("Description is short or absent — mention attachment / SAM detail dependency in missing_fields if appropriate.")

    sig["analysis_hints"] = hints
    sig["fit_score_0_1"] = total
    return {
        "total": total,
        "components": {
            "keyword_overlap": overlap,
            "naics_bonus": naics_bonus,
            "raw_points": raw_points,
        },
        "deterministic_signals": sig,
        "note": "Heuristic fit in [0.0, 1.0] from keyword overlap + NAICS tier; 1.0 when raw >= FIT scale max.",
    }


def build_explain_rank_packet(
    profile: Dict[str, Any],
    notice: Dict[str, Any],
    deterministic: Dict[str, Any],
) -> str:
    naics_disp = notice_naics_code(notice) or "(none)"
    title_disp = str(notice.get("title") or "").strip() or "(no title)"
    excerpt = notice_description_text(notice, max_len=6000)
    sig = deterministic.get("deterministic_signals") or {}
    packet = {
        "task": "explain_rank",
        "profile": profile,
        "notice": {
            "noticeId": notice.get("noticeId"),
            "title": notice.get("title"),
            "type": notice.get("type"),
            "baseType": notice.get("baseType"),
            "solicitationNumber": notice.get("solicitationNumber"),
            "postedDate": notice.get("postedDate"),
            "responseDeadLine": notice.get("responseDeadLine"),
            "fullParentPathName": notice.get("fullParentPathName"),
            "naicsCode": notice.get("naicsCode") or naics_disp,
            "typeOfSetAside": notice.get("typeOfSetAside"),
            "typeOfSetAsideDescription": notice.get("typeOfSetAsideDescription"),
            "description_excerpt": excerpt,
        },
        "notice_rankable": {
            "naics_primary": naics_disp,
            "title": title_disp,
            "one_line": f"NAICS {naics_disp}: {title_disp}",
        },
        "deterministic_score": {
            "total": deterministic.get("total"),
            "components": deterministic.get("components"),
            "note": deterministic.get("note"),
        },
        "deterministic_signals": sig,
        "response_schema": {
            "fit_score_explanation": ["bullets tied to packet + deterministic_signals; balance keyword/domain vs NAICS tier"],
            "strong_signals": [
                "Put the single strongest capture signal FIRST (usually domain/scope from title+description, then solicitation posture, then overlap score).",
            ],
            "weak_signals": [
                "Each item a distinct insight; do not repeat NAICS tier facts (e.g. do not restate bonus + mismatch twice).",
            ],
            "risks": [
                "Only operational, competitive, or structural (BPA volume uncertainty, no set-aside, OCONUS execution, etc.); never invented abstract “scope conflicts” when the packet shows strong domain fit.",
            ],
            "missing_fields": ["gaps that block a bid decision, e.g. attachments, pricing, NAICS nuance, set-aside posture"],
            "confidence": "high | medium | low",
            "recommended_next_read": "specific doc or SAM section (e.g. BPA call structure, vehicle requirements), not generic",
        },
    }
    return json.dumps(packet, ensure_ascii=False)


_EXPLAIN_RANK_SYSTEM = """You are a procurement / capture analyst helping a human decide whether to pursue a notice.

Ground rules:
- Treat `deterministic_signals` as authoritative for **tiered** NAICS signals: exact, lineage, `naics_domain_adjacent`, or none. Never invent codes or set-asides not in the packet.
- **Graded NAICS (not binary):** Lack of exact/lineage match does **not** automatically mean “no fit.” If `naics_domain_adjacent` is true, say **partial NAICS alignment** (same coarse industry ecosystem per `naics_domain_cluster`), and combine with title/description and `keyword_overlap_score` — strong domain wording in the notice can outweigh missing exact NAICS unless signals show **no** domain adjacency **and** unrelated sectors.
- **Signal priority:** When title/description clearly match the company’s domain (e.g. vehicle / fleet / rental), that belongs in `fit_score_explanation` and **first** in `strong_signals` before generic solicitation-type bullets. Do not let NAICS prose dominate when keyword/domain evidence is strong and `naics_domain_adjacent` or lineage/exact is true.
- If `naics_profile_targets_unrelated_to_notice` is non-empty, explain **partial vs whole-profile** fit (some profile NAICS unrelated to this notice); do not claim the opportunity matches the entire profile unless justified.
- `weak_signals`: each bullet a **different** idea; never duplicate the same NAICS fact (e.g. mismatch + zero bonus).
- `risks`: only **operational**, **competitive**, or **structural** (e.g. open competition, BPA volume uncertainty, geography/POP). No vague “scope may conflict” unless the packet actually supports a tension.
- `missing_fields`: not empty when `analysis_hints` is non-empty; list concrete gaps (attachments, pricing, etc.).
- `recommended_next_read`: concrete (e.g. vehicle requirements, BPA call structure), not “read the deadline” alone.
- `confidence`: high only when strongest signals align and major contradictions are absent.

Output JSON only, matching the user packet `response_schema` keys."""


_SCHEMA_REMINDER = (
    "Reply with JSON only. Keys: fit_score_explanation, strong_signals, weak_signals, "
    "risks, missing_fields, confidence (high|medium|low), recommended_next_read. "
    "Use deterministic_signals for graded NAICS (exact / lineage / domain / none); prioritize title+description "
    "domain match and keyword_overlap; strongest signal first in strong_signals."
)


def run_explain_rank(
    profile: Dict[str, Any],
    notice: Dict[str, Any],
    *,
    model: Optional[str] = None,
) -> Tuple[Optional[ExplainRankResponse], str]:
    """
    Call the configured analysis model once; validate JSON; on failure retry with stricter reminder.
    """
    det = naive_deterministic_fit(profile, notice)
    user = build_explain_rank_packet(profile, notice, det) + "\n\n" + _SCHEMA_REMINDER
    m = _resolve_analysis_model(model)
    raw = ""
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n\nIf any field is unknown from the packet, use an empty string or empty array. JSON only."
        raw = ollama_chat(model=m, user=user + suffix, system=_EXPLAIN_RANK_SYSTEM, format_json=True)
        try:
            obj = json.loads(extract_json_object(raw))
            parsed = ExplainRankResponse.model_validate(obj)
            return parsed, raw
        except Exception:
            continue
    return None, raw


def format_explain_rank_fallback(deterministic: Dict[str, Any]) -> str:
    sig = deterministic.get("deterministic_signals")
    sig_s = json.dumps(sig, ensure_ascii=False)[:1200] if isinstance(sig, dict) else str(sig)
    return (
        "Model returned invalid JSON; showing deterministic layer only.\n"
        f"  heuristic total: {deterministic.get('total')}\n"
        f"  components: {deterministic.get('components')}\n"
        f"  deterministic_signals: {sig_s}\n"
        f"  note: {deterministic.get('note')}"
    )


class SummarizeResponse(BaseModel):
    summary_bullets: List[str] = Field(default_factory=list)
    caveats: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)

    @field_validator("summary_bullets", "caveats", "next_steps", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> List[str]:
        return _coerce_str_list(v)


def build_summarize_packet(profile: Dict[str, Any], notice: Dict[str, Any]) -> str:
    packet = {
        "task": "summarize_notice",
        "profile": profile,
        "notice": {
            "noticeId": notice.get("noticeId"),
            "title": notice.get("title"),
            "type": notice.get("type"),
            "solicitationNumber": notice.get("solicitationNumber"),
            "postedDate": notice.get("postedDate"),
            "responseDeadLine": notice.get("responseDeadLine"),
            "fullParentPathName": notice.get("fullParentPathName"),
            "naicsCode": notice.get("naicsCode"),
            "description_excerpt": (str(notice.get("description") or ""))[:8000],
        },
        "response_schema": {
            "summary_bullets": ["short procurement-style bullets"],
            "caveats": ["what is unknown or not in the text"],
            "next_steps": ["e.g. read attachment, confirm NAICS, check set-aside"],
        },
    }
    return json.dumps(packet, ensure_ascii=False)


_SUMMARIZE_REMINDER = (
    "Reply with JSON only: summary_bullets (array), caveats (array), next_steps (array). "
    "Ground only in the notice excerpt and profile."
)


def run_summarize_notice(
    profile: Dict[str, Any],
    notice: Dict[str, Any],
    *,
    model: Optional[str] = None,
) -> Tuple[Optional[SummarizeResponse], str]:
    user = build_summarize_packet(profile, notice) + "\n\n" + _SUMMARIZE_REMINDER
    m = _resolve_analysis_model(model)
    raw = ""
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n\nJSON only; empty arrays allowed."
        raw = ollama_chat(model=m, user=user + suffix, system=None, format_json=True)
        try:
            obj = json.loads(extract_json_object(raw))
            return SummarizeResponse.model_validate(obj), raw
        except Exception:
            continue
    return None, raw
