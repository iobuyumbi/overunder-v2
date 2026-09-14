"""VIP-style daily report rendering (the format your channel already uses)."""

from .history import yesterday_record


def render_report(picks, day=None, title="Over / Under 2.5"):
    lines = []
    bar = "═" * 46
    lines.append(f"║       ♟  VIP · DEEP ANALYSIS REPORT        ║")
    lines.append(f"╠{bar}╣")
    lines.append(f'║  Channel: {title:<33}║')
    lines.append(f"║  Window: upcoming fixtures                 ║")
    lines.append(f"╚{bar}╝")
    lines.append("")
    lines.append("⚽️ Over/Under 2.5 picks")
    lines.append("")
    lines.append("📌 YESTERDAY")
    lines.append("")
    lines.append(f"  📊 Record: {yesterday_record()}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("📅 TODAY")
    lines.append("")
    lines.append("🟢 Over 2.5 goals")
    lines.append("")
    premiers = [p for p in picks if p.get("tier", "").startswith("🔥")]
    solids = [p for p in picks if p.get("tier", "").startswith("✅")]
    if premiers:
        lines.append("  🔥 Premium picks")
        lines.append("")
        for p in premiers:
            lines.extend(_pick_block(p))
    if solids:
        lines.append("  ✅ Solid picks")
        lines.append("")
        for p in solids:
            lines.extend(_pick_block(p))
    return "\n".join(lines)


def _pick_block(p):
    sig = p.get("statarea_signal", "NOT_FOUND")
    sig_note = {"AGREE_OVER": "✓ statarea agrees",
                "AGREE_UNDER": "✗ statarea leans UNDER",
                "DIVERGE": f"~ statarea {p['statarea']['over25']}% (diverges)",
                "NOT_FOUND": "· not on statarea card"}.get(sig, "")
    b = [
        f"  {p.get('num','?')}. {p['home']} vs {p['away']}",
        f"     Date: {p['date']}",
        f"     League: {p['league']}",
        f"     Pick: Over {p.get('line',2.5)} · {'High' if p['confidence']>=0.7 else 'Medium'} confidence ({p['confidence']*100:.1f}%)",
        f"     Category:",
        f"       • Tier: {p['tier']}" + (f"   [{sig_note}]" if sig_note else ""),
        f"     Suggested stake: {p['stake_pct']}% @ {p.get('odds',2.0)}",
        f"     Value — EV: +{p['edge_pct']}c/$  ·  Edge +{p['edge_pct']}%",
        f"     xG forecast — {p['xg'][0]}–{p['xg'][1]}",
        f"     Profile: {p['checks_passed']}/{p['checks_total']} checks passed",
    ]
    if p.get("missed"):
        shown = "; ".join(p["missed"][:3])
        more = f" (+{len(p['missed'])-3} more)" if len(p["missed"]) > 3 else ""
        b.append(f"     Missed: {shown}{more}")
    b.append("")
    return b
