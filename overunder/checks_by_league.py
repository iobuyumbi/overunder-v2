"""Per-league check analysis: which rule checks are failing us most, per
competition, grouped by settled W/L results.

Settled history stores only the RENDERED label of the CORE checks that a pick
missed (from `predict.build_pick`'s `missed` list), not the raw check-id →
bool dict.  So we key on the check LABEL (which is deterministic after
OU_FREQ substitution at the time of the prediction) and call it a "check" for
reporting purposes.  This avoids any heuristic reverse-mapping guesswork and
matches exactly what the user saw when the pick was emitted.

Usage (direct):
    from overunder.checks_by_league import per_league_check_summary
    summary = per_league_check_summary()   # -> {league_key: {...}}

Each summary row, per (league, check_label):
    n_picks      picks where this check was RELEVANT (applies to the market)
    missed       picks where the check FAILED (showed up in record["missed"])
    missed_w     count of those misses that ended in a W for us
    missed_l     count of those misses that ended in an L for us
    passed_w     picks where the check passed AND the pick won
    passed_l     picks where the check passed AND the pick lost
    miss_rate    missed / n_picks
    win_when_missed   missed_w / missed   (expected: LOW = the missed check
                                            "was onto something" and we should
                                            weigh it harder / gate on it)
    win_when_passed   passed_w / passed   (expected: HIGH)
    delta        win_when_passed - win_when_missed   (positive = this check
                                            actually helps us discriminate;
                                            higher = the check earns its keep)
"""

from collections import defaultdict

from . import history as hist
from .rules import CHECK_NAMES
from .predict import CORE_CHECKS
from .leagues import league_key


# For a given market pick, the relevant check labels = CORE_CHECKS rendered by
# CHECK_NAMES.  Some CHECK_NAMES have f-string substitutions driven by OU_FREQ
# at load time; by reading CHECK_NAMES at analysis time we get the same
# rendered label that was stamped into the `missed` list when the pick was
# generated.  This means toggling OU_FREQ between generate/analyze can
# desync labels -- acceptable because settled picks freeze their label at
# generation time and OU_FREQ rarely changes.
def _relevant_check_labels(market):
    return tuple(CHECK_NAMES.get(cid, f"[unknown check {cid}]")
                 for cid in CORE_CHECKS.get(market, ()))


def _missed_label_set(record):
    out = set()
    for m in record.get("missed", ()):
        if m.endswith(" (failed)"):
            out.add(m[: -len(" (failed)")])
        else:
            out.add(m)
    return out


def per_league_check_summary(min_picks_per_league=1):
    """{league_display: {"league_key": str, "total_picks": int,
                          "total_w": int, "total_l": int,
                          "total_win_pct": float,
                          "checks": {check_label: row_dict}}}.

    Leagues are sorted worst-first by total_win_pct, then fewest picks.
    Within each league, checks are sorted worst-first by `delta` descending
    (most discriminative checks first, so the user sees "which checks, when
    missed, cause us to lose").
    """
    records = [r for r in hist._load()["settled"]
               if r.get("result") in ("W", "L")]
    by_lg = defaultdict(list)
    for r in records:
        by_lg[league_key(r.get("league"))].append(r)
    out = {}
    for lgk, recs in by_lg.items():
        if len(recs) < min_picks_per_league:
            continue
        total = len(recs)
        tw = sum(1 for r in recs if r["result"] == "W")
        tl = total - tw
        wp = round(100 * tw / total, 1) if total else 0.0
        display = (recs[0].get("league") or lgk).title()
        # Row per check label, aggregated across picks in this league
        rows = defaultdict(lambda: dict(
            n_picks=0, missed=0, missed_w=0, missed_l=0,
            passed_w=0, passed_l=0,
        ))
        for r in recs:
            is_w = r["result"] == "W"
            missed_set = _missed_label_set(r)
            for label in _relevant_check_labels(r.get("market", "")):
                row = rows[label]
                row["n_picks"] += 1
                if label in missed_set:
                    row["missed"] += 1
                    if is_w:
                        row["missed_w"] += 1
                    else:
                        row["missed_l"] += 1
                else:
                    if is_w:
                        row["passed_w"] += 1
                    else:
                        row["passed_l"] += 1
        # Compute derived fields
        for label, row in rows.items():
            n, miss = row["n_picks"], row["missed"]
            passed = n - miss
            row["miss_rate"] = round(100 * miss / n, 1) if n else 0.0
            row["win_when_missed"] = (
                round(100 * row["missed_w"] / miss, 1) if miss else None)
            row["win_when_passed"] = (
                round(100 * row["passed_w"] / passed, 1) if passed else None)
            if row["win_when_missed"] is not None \
                    and row["win_when_passed"] is not None:
                row["delta"] = round(row["win_when_passed"]
                                     - row["win_when_missed"], 1)
            else:
                row["delta"] = None
        # Sort checks inside the league: biggest positive delta first (most
        # discriminative = when missed, we lose badly), then by miss_rate
        # desc, then by n_picks desc.
        def _sort_key(kv):
            r = kv[1]
            return (-(r["delta"] if r["delta"] is not None else -9999),
                    -r["miss_rate"],
                    -r["n_picks"])
        sorted_checks = dict(sorted(rows.items(), key=_sort_key))
        out[display] = dict(
            league_key=lgk,
            total_picks=total, total_w=tw, total_l=tl,
            total_win_pct=wp,
            checks=sorted_checks,
        )
    # Sort leagues worst-first by win% then picks desc
    return dict(sorted(
        out.items(),
        key=lambda kv: (kv[1]["total_win_pct"], -kv[1]["total_picks"])
    ))
