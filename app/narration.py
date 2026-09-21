"""
narration.py — EVIDENCE JSON -> COO answer.

Plain business language for a non-technical executive. Rules enforced here:
- Lead with the answer; methodology never comes first.
- No Python/SQL/statistics/model jargon, no internal variable names,
  no implementation thresholds, no unexplained abbreviations.
- Counts render as integers; percentages keep their evidence precision.
- complaint_rate and late_order_rate are never interchanged; rider complaint
  shares are never presented as delivery-lateness rates.
- One short "Data note:" closes each answer; limitations are stated once.
- Findings are signals to investigate, never proof of cause, never blame.

Primary: deterministic templates (always available, zero cost).
Optional: one Gemini call that rephrases ONLY the supplied evidence.
Gemini NEVER calculates, NEVER invents numbers, NEVER claims causation.
"""
from __future__ import annotations
import json
import re


def _int(x) -> int:
    """Coerce count fields to int so they never render as floats (e.g. 12.0)."""
    try:
        return int(round(float(x)))
    except Exception:
        return 0


def _pct(x) -> str:
    """Render a percentage keeping evidence precision, no trailing '.0'."""
    try:
        return f"{float(x):g}"
    except Exception:
        return str(x)


def _whole(x) -> str:
    """Whole-percent rendering for readability (presentation rounding only)."""
    try:
        return f"{round(float(x)):d}"
    except Exception:
        return str(x)


_LATE_MEANING = ("An order counts as late when its delivery time is unusually "
                 "long compared with that branch's own history.")

_DATA_NOTE_BASE = ("These findings are indicators for investigation, not proof "
                   "of the underlying cause. The dataset appears to be a partial "
                   "extract rather than a complete transaction history, and order "
                   "volumes vary substantially between months.")


def data_note(tool_name: str, result: dict) -> str:
    """Single plain-language data note for an answer. Replaces verbatim
    technical caveats in COO-facing output (raw evidence stays in the app's
    collapsed Evidence panel for transparency)."""
    if tool_name in ("branch_delivery_trend", "branch_worsening_reasons",
                     "rider_performance", "anomaly_scan"):
        return f"Data note: {_LATE_MEANING} {_DATA_NOTE_BASE}"
    if tool_name == "late_complaint_breakdown":
        data = result.get("answer_data") or {}
        cov = ""
        try:
            total = _int(data.get("comment_count", data.get("total_comments", 0)))
            late = _int(data.get("late_order_complaint_count",
                                 data.get("late_complaints_found", 0)))
            cov = (f" About {total:,} orders included a comment, of which {late:,} "
                   f"mentioned lateness — conclusions only reflect orders where "
                   f"customers wrote something.")
        except Exception:
            pass
        return f"Data note: {_DATA_NOTE_BASE}{cov}"
    return f"Data note: {_DATA_NOTE_BASE}"


def _missing_answer(tool_name: str) -> str:
    specifics = {
        "branch_delivery_trend":
            "The available evidence does not contain enough information to say "
            "which branch got worse.",
        "branch_worsening_reasons":
            "The available evidence does not contain enough information to break "
            "down that branch.",
        "late_complaint_breakdown":
            "The available evidence does not currently include enough information "
            "to identify the peak hour and day for late-delivery complaints.",
        "rider_performance":
            "The available evidence does not contain enough information to rank "
            "riders reliably.",
        "anomaly_scan":
            "The available evidence does not currently point to a specific concern.",
    }
    return ("I couldn't find enough reliable data to answer that. "
            + specifics.get(tool_name, "The available evidence is insufficient."))


def template_narration(tool_name: str, result: dict) -> str:
    data = result.get("answer_data")
    if data is None:
        return _missing_answer(tool_name) + "\n\n" + data_note(tool_name, result)

    if tool_name == "branch_delivery_trend":
        worsened = data.get("branches_worsened", [])[:5]
        if not worsened:
            return ((f"Comparing {data['compared_months'][0]} to {data['compared_months'][1]}, "
                     "no branch shows a reliable worsening signal.") + "\n\n"
                    + data_note(tool_name, result))
        prev_m, last_m = data["compared_months"][0], data["compared_months"][1]
        top = worsened[0]
        lines = [
            (f"{top['BranchID']} got worse more than any other branch: its late-delivery "
             f"rate increased from {_whole(top['late_rate_prev'] * 100)}% in {prev_m} "
             f"to {_whole(top['late_rate_last'] * 100)}% in {last_m}, "
             f"based on {_int(top['n_last'])} orders."),
        ]
        rest = worsened[1:5]
        if rest:
            lines += ["", "Other branches that got worse:"]
            for b in rest:
                lines.append(
                    f"- {b['BranchID']}: late deliveries increased from "
                    f"{_whole(b['late_rate_prev'] * 100)}% in {prev_m} to "
                    f"{_whole(b['late_rate_last'] * 100)}% in {last_m}, "
                    f"based on {_int(b['n_last'])} orders."
                )
        lines += ["", data_note(tool_name, result)]
        return "\n".join(lines)

    if tool_name == "branch_worsening_reasons":
        p, l = data["prev"], data["last"]
        prev_m, last_m = data["months"][0], data["months"][1]
        lines = [
            (f"In {data['branch']}, late deliveries increased from {p['late_rate_pct']}% "
             f"in {prev_m} to {l['late_rate_pct']}% in {last_m}, while the average "
             f"customer rating moved from {p['avg_rating']} to {l['avg_rating']}. "
             f"This is based on {_int(p['n'])} orders in {prev_m} and {_int(l['n'])} "
             f"orders in {last_m}."),
            "",
            "Breaking down where the extra time appeared:",
            (f"- Time from order creation to rider assignment: {p['dispatch_min']} "
             f"minutes -> {l['dispatch_min']} minutes."),
            (f"- Time from assignment to pickup: {p['pickup_min']} -> {l['pickup_min']} minutes."),
            (f"- Overall delivery time: {p['delivery_min']} -> {l['delivery_min']} minutes."),
        ]
        if l["dispatch_min"] > p["dispatch_min"] * 1.3:
            lines.append("The biggest change was in the time before a rider was assigned, "
                         "which suggests dispatch is a possible area to investigate — "
                         "not proof of the cause.")
        elif l["pickup_min"] > p["pickup_min"] * 1.3:
            lines.append("The biggest change was in the time between assignment and pickup, "
                         "which suggests the pickup stage is a possible area to investigate — "
                         "not proof of the cause.")
        else:
            lines.append("No single stage dominates; the change is spread across stages, "
                         "so this warrants a broader look rather than pointing at one cause.")
        lines += ["", data_note(tool_name, result)]
        return "\n".join(lines)

    if tool_name == "late_complaint_breakdown":
        # Answer the question FIRST with peak hour/day by complaint COUNT,
        # then supporting zone/branch/rider findings. Shares below are the
        # share of orders that produced a late-delivery complaint — never
        # delivery-lateness rates, and never attributed as rider fault.
        by_hour = data.get("complaints_by_hour_of_day", {}) or {}
        by_dow = data.get("complaints_by_day_of_week", {}) or {}
        try:
            peak_h, peak_h_n = max(by_hour.items(), key=lambda kv: float(kv[1])) if by_hour else ("n/a", 0)
        except Exception:
            peak_h, peak_h_n = ("n/a", 0)
        try:
            peak_d, peak_d_n = max(by_dow.items(), key=lambda kv: float(kv[1])) if by_dow else ("n/a", 0)
        except Exception:
            peak_d, peak_d_n = ("n/a", 0)
        total_c = _int(data.get("comment_count", data.get("total_comments", 0)))
        late_c = _int(data.get("late_order_complaint_count", data.get("late_complaints_found", 0)))
        lines = [
            (f"Yes. Late-delivery complaints cluster in specific places and times. "
             f"The busiest hour is {peak_h}:00 with {_int(peak_h_n)} complaints, "
             f"and {peak_d} stands out with {_int(peak_d_n)} complaints "
             f"(out of {late_c:,} late-delivery complaints in {total_c:,} comments)."),
            "",
            ("Below, each percentage is the share of orders in that area, branch, or "
             "with that rider that produced a late-delivery complaint — a measure of "
             "where complaints concentrate, not a delivery-lateness rate and not an "
             "assessment of any individual."),
            "",
            "Top zones by complaint count:",
        ]
        for z in data.get("top_zones_by_complaint_volume", [])[:5]:
            lines.append(f"- {z['DeliveryZoneName']}: {_int(z['complaints'])} complaints "
                         f"out of {_int(z['total_orders'])} orders ({z['complaint_rate_pct']}%)")
        lines.append("Top branches by complaint count:")
        for b in data.get("top_branches_by_complaint_volume", [])[:5]:
            lines.append(f"- {b['BranchID']}: {_int(b['complaints'])} complaints "
                         f"out of {_int(b['total_orders'])} orders ({b['complaint_rate_pct']}%)")
        lines.append("Top riders by complaint count:")
        for r in data.get("top_riders_by_complaint_volume", [])[:5]:
            lines.append(f"- {r['RiderID']}: {_int(r['complaints'])} complaints "
                         f"out of {_int(r['total_orders'])} orders ({r['complaint_rate_pct']}%)")
        lines += ["", data_note(tool_name, result)]
        return "\n".join(lines)

    if tool_name == "rider_performance":
        window = data["window"]
        overall = _pct(data["overall_late_rate_pct"])
        lead_list = data["best_riders"] if data.get("direction_requested") == "best" else data["worst_riders"]
        other_list = data["worst_riders"] if data.get("direction_requested") == "best" else data["best_riders"]
        lead_word = "best" if data.get("direction_requested") == "best" else "worst"
        lines = []
        if data.get("single_rider"):
            s = data["single_rider"]
            lines.append(
                f"Rider {s['RiderID']} had a late-delivery rate of {_pct(s['late_rate_pct'])}% "
                f"across {_int(s['n'])} orders in {window}, compared with about {overall}% overall. "
                f"That ranks #{_int(s['rank_by_late_rate'])} of {_int(s['rank_out_of'])} riders "
                f"ordered from most to fewest late deliveries."
            )
            lines.append(f"Their typical delivery time was {_int(s['avg_delivery_min'])} minutes, "
                         f"with an average customer rating of {s['avg_rating']}.")
            lines.append("")
        elif lead_list:
            top = lead_list[0]
            if lead_word == "worst":
                lines.append(
                    f"Rider {top['RiderID']} had the highest late-delivery rate among riders "
                    f"with enough orders for a reliable comparison in {window}: "
                    f"{_pct(top['late_rate_pct'])}% across {_int(top['n'])} orders, "
                    f"compared with about {overall}% overall."
                )
            else:
                lines.append(
                    f"Rider {top['RiderID']} had the lowest late-delivery rate among riders "
                    f"with enough orders for a reliable comparison in {window}: "
                    f"{_pct(top['late_rate_pct'])}% across {_int(top['n'])} orders, "
                    f"compared with about {overall}% overall."
                )
            lines.append(f"Their typical delivery time was {_int(top['avg_delivery_min'])} minutes, "
                         f"with an average customer rating of {top['avg_rating']}.")
            lines.append("")
        lines.append(f"The full top {len(lead_list)} "
                     f"({'fewest' if lead_word == 'best' else 'most'} late deliveries first):")
        for r in lead_list:
            above_below = "above" if r["vs_avg_pp"] >= 0 else "below"
            lines.append(
                f"- {r['RiderID']}: {_pct(r['late_rate_pct'])}% of orders late "
                f"(about {_int(abs(r['vs_avg_pp']))} percentage points {above_below} average), "
                f"rating {r['avg_rating']}, typical delivery {_int(r['avg_delivery_min'])} min, "
                f"{_int(r['n'])} orders"
            )
        if other_list and not data.get("single_rider"):
            ctx_word = "lowest" if lead_word == "worst" else "highest"
            lines.append(f"For context, riders at the {ctx_word} end:")
            for r in other_list[:3]:
                lines.append(
                    f"- {r['RiderID']}: {_pct(r['late_rate_pct'])}% of orders late, "
                    f"rating {r['avg_rating']}, {_int(r['n'])} orders"
                )
        lines.append("")
        lines.append("A high rate warrants investigation — it can reflect a harder route or "
                     "dispatch delays, not necessarily the rider. " + data_note(tool_name, result))
        return "\n".join(lines)

    if tool_name == "anomaly_scan":
        findings = data.get("operational_findings", []) or []
        prev_m, last_m = data["compared_months"][0], data["compared_months"][1]
        branch_jumps = [f for f in findings if f.get("type") == "branch_late_rate_jump"]
        rider_flags = [f for f in findings if f.get("type") == "rider_high_late_rate"]
        rating_drops = [f for f in findings if f.get("type") == "branch_rating_drop"]

        if not findings:
            return ("Based on the available data, nothing currently stands out as a concern. "
                    "No branch, rider group, or rating pattern moved unusually this period."
                    "\n\n" + data_note(tool_name, result))

        # Bottom line names the most concerning entities directly from evidence.
        bits = []
        if branch_jumps:
            bistrs = list(dict.fromkeys(str(f.get("branch", ""))
                                        for f in branch_jumps if f.get("branch")))
            bits.append(f"late deliveries rose sharply at {', '.join(bistrs[:3])}"
                        + (" and others" if len(bistrs) > 3 else ""))
        if rider_flags:
            bits.append("a small group of riders shows unusually high late-delivery rates")
        if rating_drops:
            bits.append("customer ratings deteriorated sharply at several branches")
        lines = ["### Bottom line",
                 f"Yes. {', '.join(bits)}. Each of these warrants investigation.",
                 "", "### What stands out"]

        if branch_jumps:
            lines.append("")
            lines.append("**1. Branch performance**")
            for f in branch_jumps[:5]:
                lines.append(f"- {_branch_jump_sentence(f, prev_m, last_m)}")
        if rider_flags:
            lines.append("")
            lines.append("**2. Rider performance**")
            lines.append(_rider_group_sentence(rider_flags))
            for f in rider_flags[:5]:
                rid = f.get("rider", "A rider")
                m = re.search(r"([\d.]+)%\s+vs a ([\d.]+)%.*?over (\d+) orders", f.get("detail", ""))
                if m:
                    lines.append(f"- Rider {rid} had a {_whole(m.group(1))}% late-delivery rate "
                                 f"across {_int(m.group(3))} orders.")
                else:
                    lines.append(f"- Rider {rid} shows an unusually high late-delivery rate.")
        if rating_drops:
            lines.append("")
            lines.append("**3. Customer experience**")
            for f in rating_drops[:5]:
                lines.append(f"- {_rating_drop_sentence(f, prev_m, last_m)}")
            lines.append("Sharp rating drops may indicate deteriorating customer experience and "
                         "should be reviewed alongside delivery performance.")

        lines += ["", "### What to investigate"]
        if branch_jumps and branch_jumps[0].get("branch"):
            lines.append(f"- Ask the {branch_jumps[0]['branch']} manager what changed in {last_m} "
                         f"(staffing, demand spikes, local disruptions).")
        if rider_flags:
            lines.append("- Review the flagged riders' routes and dispatch patterns before drawing "
                         "any conclusions about individuals.")
        if rating_drops and rating_drops[0].get("branch"):
            lines.append(f"- Compare the rating drops with delivery performance at the same branches.")
        lines += ["", "### Data note",
                    data_note(tool_name, result).replace("Data note: ", "", 1)]
        # Translate raw data-quality flags into operational implications.
        dq_line = _dq_sentence(data.get("data_quality_flags", {}) or {})
        if dq_line:
            lines.append(dq_line)
        return "\n".join(lines)

    return json.dumps(data, default=str, indent=2)


def _branch_jump_sentence(f: dict, prev_m: str, last_m: str) -> str:
    bid = f.get("branch", "A branch")
    m = re.search(r"\(([\d.]+)%\s*->\s*([\d.]+)%\).*?n=(\d+)", f.get("detail", ""))
    if m:
        return (f"{bid} stands out: its late-delivery rate increased from {_whole(m.group(1))}% "
                f"in {prev_m} to {_whole(m.group(2))}% in {last_m}, based on {_int(m.group(3))} orders.")
    return f"{bid} showed a notable increase in late deliveries between {prev_m} and {last_m}."


def _rating_drop_sentence(f: dict, prev_m: str, last_m: str) -> str:
    bid = f.get("branch", "A branch")
    m = re.search(r"from ([\d.]+) to ([\d.]+).*?n=(\d+)", f.get("detail", ""))
    if m:
        return (f"{bid}: average customer rating fell from {m.group(1)} to {m.group(2)} "
                f"between {prev_m} and {last_m}, across {_int(m.group(3))} orders.")
    return f"{bid} showed a notable drop in average customer rating."


def _rider_group_sentence(rider_flags: list) -> str:
    rates = []
    for f in rider_flags:
        m = re.search(r"([\d.]+)%\s+vs a ([\d.]+)%", f.get("detail", ""))
        if m:
            rates.append((float(m.group(1)), float(m.group(2))))
    if rates:
        top = max(r[0] for r in rates)
        avg = rates[0][1]
        return (f"Several riders had late-delivery rates above {_whole(top)}%, compared with "
                f"an overall rate of about {_whole(avg)}%. Rider identifiers are retained below; "
                f"a high rate warrants investigation, not conclusions about any individual.")
    return ("Several riders show unusually high late-delivery rates. Rider identifiers are "
            "retained below; a high rate warrants investigation, not conclusions about "
            "any individual.")


def _dq_sentence(dq: dict) -> str:
    bits = []
    try:
        if float(dq.get("pct_negative_pickup_lag", 0) or 0) > 1:
            bits.append("a substantial share of records contains inconsistent timing information, "
                        "which may affect the reliability of some delivery-time analyses")
    except Exception:
        pass
    try:
        if int(dq.get("zero_rating_orders", 0) or 0) > 0:
            bits.append("many orders have no customer rating, so rating-based conclusions do not "
                        "represent every order")
    except Exception:
        pass
    months = dq.get("months_with_under_1000_orders") or []
    if months:
        bits.append("some months contain unusually few orders, so comparisons spanning those "
                    "months should be treated as directional")
    if not bits:
        return ""
    return "On data reliability: " + "; ".join(bits) + "."


def render(tool_name: str, result: dict) -> str:
    return template_narration(tool_name, result)


def narrate_with_gemini(tool_name: str, result: dict) -> tuple[str | None, dict]:
    """Try one Gemini narration call. Returns (text, usage_info) or (None, {})."""
    try:
        from gemini_client import get_client, model_name
    except ImportError:
        try:
            from app.gemini_client import get_client, model_name
        except Exception:
            return None, {}
    client = get_client()
    if client is None:
        return None, {}
    data = result.get("answer_data")
    if data is None:
        return None, {}
    evidence = json.dumps({"tool": tool_name, "evidence": data,
                           "caveats": result.get("caveats", [])}, default=str)[:12000]
    prompt = NARRATION_SYSTEM + f"\nEVIDENCE:\n{evidence}\nAnswer:"
    raw = ""
    in_tok = out_tok = 0
    estimated = True
    try:
        resp = client.models.generate_content(
            model=model_name(),
            contents=prompt,
            config={"temperature": 0},
        )
        raw = (getattr(resp, "text", "") or "").strip()
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
            out_tok = int(getattr(um, "candidates_token_count", 0) or 0)
            if in_tok or out_tok:
                estimated = False
        if estimated:
            try:
                from api_usage import estimate_tokens_fallback
            except ImportError:
                from app.api_usage import estimate_tokens_fallback
            in_tok = estimate_tokens_fallback(prompt)
            out_tok = estimate_tokens_fallback(raw)
    except Exception:
        return None, {}
    try:
        try:
            from api_usage import log_call
        except ImportError:
            from app.api_usage import log_call
        log_call("narration", in_tok, out_tok, estimated=estimated)
    except Exception:
        pass
    if not raw:
        return None, {}
    return raw, {"in": in_tok, "out": out_tok, "estimated": estimated}


def narrate(tool_name: str, result: dict, use_gemini: bool = True) -> tuple[str, str]:
    """Returns (text, method). method is 'gemini' or 'template'. Templates always win on failure."""
    if use_gemini:
        text, _ = narrate_with_gemini(tool_name, result)
        if text:
            return text, "gemini"
    return template_narration(tool_name, result), "template"


NARRATION_SYSTEM = """You are an operations intelligence assistant serving a NON-TECHNICAL COO. Translate the analytical evidence into clear, concise, business-oriented operational insight.

CORE PRINCIPLE: answer the business question first. Explain operational significance second. Mention methodology or data limits only when they materially affect interpretation — once, at the end, briefly.

HARD RULES:
- Use ONLY numbers present in the evidence; never invent or recalculate numbers. Render counts as integers, never floats.
- Plain business language only. Say "late-delivery rate", "percentage points", "orders". NEVER expose Python, SQL, DataFrames, variable names (n_last, late_rate_prev, MIN_VOLUME, ...), thresholds, model terms, or abbreviations like pp. Never call the historical branch threshold an SLA.
- Lead with the answer, never with methodology, evidence extracts, caveats, or missing fields. If something requested is missing from evidence, first answer what can be answered, then add one sentence naming the gap.
- Structure broad answers as: Bottom line / What stands out / What to investigate / Data note. Keep it concise.
- Metric separation is absolute: complaint shares (share of orders producing a late-delivery complaint) are NEVER called delivery-lateness rates, and vice versa. Use the evidence's metric_definitions denominators; do not rename metrics.
- For complaint evidence, answer peak hour and peak day first. For rider evidence, describe the metric and keep rider IDs as identifiers; never imply personal fault.
- Findings are signals to investigate ("This warrants investigation", "The data shows", "A possible area to investigate is"). NEVER claim causation ("caused", "the reason is", "underperforming because of") and never recommend discipline.
- Data-quality flags become one short operational-confidence note (implications, not raw flags). Mention partial-extract/monthly-volume limits once, not repeatedly.
- An order counts as late when its delivery time is unusually long compared with that branch's own history. Never call this an SLA.
- Return plain text only."""
