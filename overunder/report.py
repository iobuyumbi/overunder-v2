"""VIP-style daily report rendering (the format your channel already uses)."""

import datetime

from .history import yesterday_record

SECTION_ICONS = {"over": "🟢", "under": "🔴", "btts": "🔵", "no_btts": "🚫",
                 "home": "🏠", "home_sc": "🎯", "away_sc": "🎯",
                 "over15": "🟢", "under35": "🔴", "home_dw": "🛡"}


def _day_label(d_iso, today_iso=None):
    if today_iso is None:
        today_iso = datetime.date.today().isoformat()
    if d_iso == today_iso:
        return f"📅 TODAY ({d_iso})"
    try:
        d = datetime.date.fromisoformat(d_iso)
        t = datetime.date.fromisoformat(today_iso)
        delta = (d - t).days
        if delta == 1:
            return f"📅 TOMORROW ({d_iso})"
        if delta > 1:
            return f"📅 +{delta}d ({d_iso})"
        if delta == -1:
            return f"📅 YESTERDAY ({d_iso})"
        if delta < -1:
            return f"📅 {delta}d ({d_iso})"
    except (ValueError, TypeError):
        pass
    return f"📅 {d_iso}"


def render_report(picks, day=None, title="Over / Under 2.5 + BTTS + Home",
                  day_diagnostics=None):
    """Render the VIP report.

    picks             — list of pick dicts (may span multiple dates)
    day               — optional ISO date; if set, used as the 'today' baseline
                        for day labels; otherwise real system date is used
    title             — banner channel name
    day_diagnostics   — optional {iso_date: {"total": N, "results": N,
                        "fixtures": N, "qualified": N}} dict for per-day counts
    """
    lines = []
    bar = "═" * 46
    lines.append("║       ♟  VIP · DEEP ANALYSIS REPORT        ║")
    lines.append(f"╠{bar}╣")
    lines.append(f"║  Channel: {title[:33]:<33}║")
    lines.append("║  Window: upcoming fixtures                 ║")
    lines.append(f"╚{bar}╝")
    lines.append("")
    lines.append("📌 YESTERDAY")
    lines.append("")
    lines.append(f"  📊 Record: {yesterday_record()}")
    lines.append("")
    lines.append("---")
    lines.append("")

    today_iso = day or datetime.date.today().isoformat()
    dates_in_picks = sorted({p["date"] for p in picks})
    diag_keys = sorted(day_diagnostics.keys()) if day_diagnostics else []
    all_dates = sorted(set(dates_in_picks) | set(diag_keys))

    if not all_dates:
        lines.append(f"  (no picks and no diagnostics provided — nothing to report)")
        return "\n".join(lines)

    for d_iso in all_dates:
        lines.append(_day_label(d_iso, today_iso))
        lines.append("")
        diag = (day_diagnostics or {}).get(d_iso)
        if diag:
            parts = []
            if "total" in diag and "results" in diag:
                parts.append(f"{diag['results']}/{diag['total']} already played")
            if "fixtures" in diag:
                played = diag.get("results", diag.get("total", diag["fixtures"]) - diag["fixtures"])
                parts.append(f"{diag['fixtures']} upcoming fixtures")
            if "qualified" in diag:
                parts.append(f"{diag['qualified']} qualifying picks")
            if parts:
                lines.append("  📈 " + " · ".join(parts))
                lines.append("")
        day_picks = [p for p in picks if p["date"] == d_iso]
        if not day_picks:
            lines.append("  (no qualifying picks for this date)")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue
        markets = []
        for p in day_picks:
            if p["market"] not in markets:
                markets.append(p["market"])
        for mkt in markets:
            icon = SECTION_ICONS.get(mkt, "⚽")
            label = day_picks[[p["market"] for p in day_picks].index(mkt)]["label"]
            lines.append(f"{icon} {label}")
            lines.append("")
            premiers = [p for p in day_picks if p["market"] == mkt and p["tier"].startswith("🔥")]
            solids = [p for p in day_picks if p["market"] == mkt and p["tier"].startswith("✅")]
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
            if not premiers and not solids:
                lines.append("  (no qualified picks)")
                lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _pick_block(p):
    sig = p.get("statarea_signal", "NOT_FOUND")
    sig_note = {"AGREE_OVER": "✓ statarea agrees",
                "AGREE_UNDER": "✗ statarea leans UNDER",
                "AGREE_HOME": "✓ statarea home ≥55",
                "DIVERGE": f"~ statarea O25 {p['statarea']['over25']}% (diverges)" if p.get("statarea") else "~ diverges",
                "NOT_FOUND": "· not on statarea card"}.get(sig, "")
    pick_line = f"Over {p['line']} · " if p["market"] == "over" else ""
    b = [
        f"  {p.get('num','?')}. {p['home']} vs {p['away']}",
        f"     Date: {p['date']}",
        f"     League: {p['league']}",
        f"     Pick: {p['label']} · {'High' if p['confidence']>=0.7 else 'Medium'} confidence ({p['confidence']*100:.1f}%)",
        "     Category:",
        f"       • Tier: {p['tier']}" + (f"   [{sig_note}]" if sig_note else ""),
        f"     Suggested stake: {p['stake_pct']}% @ {p.get('odds',2.0)}",
        f"     Value — EV: +{p['edge_pct']}c/$  ·  Edge +{p['edge_pct']}%",
        f"     Team goals — Home {p.get('home_attack','?')} scored / "
        f"{p.get('home_concede','?')} conceded g/m (at home) · Away "
        f"{p.get('away_attack','?')} scored / {p.get('away_concede','?')} "
        f"conceded g/m (away)",
        f"     xG forecast — {p['xg'][0]}–{p['xg'][1]} (total)",
        f"     Profile: {p['checks_passed']}/{p['checks_total']} checks passed",
    ]
    if p.get("missed"):
        shown = "; ".join(p["missed"][:3])
        more = f" (+{len(p['missed'])-3} more)" if len(p["missed"]) > 3 else ""
        b.append(f"     Missed: {shown}{more}")
    b.append("")
    return b


def render_team_stats(team, matches):
    """Readable scoring profile: venue-split score/concede rates and trends."""
    def agg(ms):
        if not ms:
            return "  (no matches)"
        n = len(ms)
        gf = sum(m["gf"] for m in ms); ga = sum(m["ga"] for m in ms)
        over = sum(1 for m in ms if m["gf"] + m["ga"] > 2.5)
        btts = sum(1 for m in ms if m["gf"] > 0 and m["ga"] > 0)
        scor = sum(1 for m in ms if m["gf"] > 0)
        return (f"  {n} matches | {gf} scored ({gf/n:.2f}/m) | {ga} conceded "
                f"({ga/n:.2f}/m) | over2.5 {over}/{n} | BTTS {btts}/{n} | "
                f"scored {scor}/{n}")

    h = [m for m in matches if m["venue"] == "H"]
    a = [m for m in matches if m["venue"] == "A"]
    lines = [f"== TEAM SCORING PROFILE: {team} ==",
             f"last {len(matches)} matches (point-in-time, most recent last)"]
    lines.append("OVERALL" + agg(matches))
    lines.append("AT HOME" + agg(h))
    lines.append("AWAY   " + agg(a))
    lines.append("RECENT (latest 6, oldest -> newest):")
    for m in matches[-6:]:
        v = "H" if m["venue"] == "H" else "A"
        lines.append(f"  {m.get('date','?')}  {v}  {m['gf']}-{m['ga']}")
    lines.append("")
    lines.append("(rule checks need an opponent; see any pick block's "
                 "'Profile: N/17' and 'Missed' lines for those)")
    return "\n".join(lines)
