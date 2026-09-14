import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from overunder.rules import poisson_over25, run_checks
from overunder.teams import normalize, find_match
from overunder import statarea as st
from overunder.providers import DemoProvider
from overunder.predict import build_pick, predict_day
from overunder import history as hist

CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "overunder", "sample_data", "sample_card_2026-09-12.md")


def M(venue, gf, ga):
    return {"venue": venue, "gf": gf, "ga": ga, "date": "2026-09-01"}


class TestNormalize(unittest.TestCase):
    def test_prefix_strip(self):
        self.assertEqual(normalize("FC St. Gallen"), normalize("St Gallen"))
        self.assertEqual(normalize("St Gallen"), "fc st gallen")
        self.assertEqual(normalize("AFC Fylde"), normalize("Fylde"))

    def test_alias(self):
        self.assertEqual(normalize("Go A Eagles"), "go ahead eagles")
        self.assertEqual(normalize("F. Sittard"), "fortuna sittard")

    def test_find_match_fuzzy(self):
        games = [{"home": "FC St. Gallen", "away": "FC Sion"}]
        g, s = find_match("St Gallen", "Sion", games)
        self.assertIsNotNone(g)
        self.assertEqual(g["home"], "FC St. Gallen")


class TestRules(unittest.TestCase):
    def test_all_pass(self):
        home = [M("H", 3, 1), M("H", 2, 2), M("H", 3, 0), M("A", 1, 1),
                M("H", 2, 1), M("A", 2, 2)]
        away = [M("A", 3, 1), M("A", 2, 2), M("A", 3, 1), M("H", 2, 1),
                M("A", 2, 1), M("H", 1, 1)]
        checks = run_checks(home, away)
        core = [checks[k] for k in ("H1", "H2", "A1", "A2", "A3", "A4")]
        self.assertTrue(all(core))

    def test_all_fail(self):
        dead = [M("H", 0, 0), M("A", 0, 0), M("H", 0, 1), M("A", 1, 0),
                M("H", 0, 0), M("A", 0, 0)]
        checks = run_checks(dead, dead)
        self.assertFalse(any(checks[k] for k in ("H1", "H2", "A1", "A2", "A3", "A4")))

    def test_poisson_range(self):
        strong = [M("H", 3, 1)] * 6
        weak = [M("A", 1, 2)] * 6
        p, lam_h, lam_a = poisson_over25(strong, weak)
        self.assertGreater(p, 0.5)
        self.assertLess(p, 0.98)
        self.assertGreater(lam_h, lam_a)


class TestStatareaParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CARD, encoding="utf-8") as f:
            cls.games = st.parse_card(f.read())

    def test_parsed_enough(self):
        self.assertGreaterEqual(len(self.games), 60)

    def test_known_values(self):
        g, _ = find_match("St Gallen", "Sion", self.games)
        self.assertEqual(g["over25"], 74)
        g, _ = find_match("Real Madrid", "Rayo Vallecano", self.games)
        self.assertEqual(g["over25"], 82)

    def test_cross_check_signals(self):
        picks = [{"home": "St Gallen", "away": "Sion", "market": "over"},
                 {"home": "Watford", "away": "Stoke", "market": "over"},
                 {"home": "No Such", "away": "Teams", "market": "over"}]
        out = st.cross_check(picks, self.games)
        self.assertEqual(out[0]["statarea_signal"], "AGREE_OVER")
        self.assertEqual(out[1]["statarea_signal"], "DIVERGE")
        self.assertEqual(out[2]["statarea_signal"], "NOT_FOUND")


class TestPredictSettle(unittest.TestCase):
    def test_build_pick_structure(self):
        prov = DemoProvider()
        fx = prov.fixtures()[0]
        p = build_pick(fx, prov)
        for k in ("confidence", "ev", "stake_pct", "tier", "xg", "checks_passed"):
            self.assertIn(k, p)
        self.assertTrue(0 < p["confidence"] <= 0.98)

    def test_settle_and_stats(self):
        import tempfile, importlib
        os.environ["OU_DATA_DIR"] = tempfile.mkdtemp(prefix="ou_test_")
        import overunder.config as cfg
        importlib.reload(cfg)
        importlib.reload(hist)
        prov = DemoProvider()
        fx = prov.fixtures()
        picks = [build_pick(f, prov) for f in fx]
        n = hist.record_picks(picks)
        self.assertEqual(n, len(fx))
        s = hist.settle(prov.results())
        self.assertEqual(s, len(fx))
        stats = hist.stats()
        self.assertEqual(stats["settled_total"], len(fx))
        self.assertIn("by_signal", stats)


class TestMarkets(unittest.TestCase):
    def test_market_probs_sane(self):
        from overunder.rules import market_probs
        strong = [M("H", 3, 1)] * 6
        weak = [M("A", 0, 2)] * 6
        p = market_probs(strong, weak)
        self.assertGreater(p["over"], 0.5)
        self.assertGreater(p["home"], 0.5)
        self.assertLess(p["btts"], 0.5)

    def test_build_pick_all_markets(self):
        prov = DemoProvider()
        fx = prov.fixtures()[0]
        for mkt in ("over", "btts", "home"):
            p = build_pick(fx, prov, market=mkt)
            self.assertEqual(p["market"], mkt)
            self.assertTrue(0 < p["confidence"] <= 0.98)

    def test_predict_day_markets(self):
        from overunder.predict import predict_day
        prov = DemoProvider()
        picks = predict_day(prov, markets=("over", "btts", "home"))
        mkts = {p["market"] for p in picks}
        self.assertIn("over", mkts)

    def test_settle_btts(self):
        import tempfile, importlib
        os.environ["OU_DATA_DIR"] = tempfile.mkdtemp(prefix="ou_btts_")
        import overunder.config as cfg
        importlib.reload(cfg)
        importlib.reload(hist)
        prov = DemoProvider()
        fx = prov.fixtures()[0]
        p = build_pick(fx, prov, market="btts")
        hist.record_picks([p])
        n = hist.settle([{"home": fx["home"], "away": fx["away"], "hg": 1, "ag": 1}])
        self.assertEqual(n, 1)


class TestStatareaHeaderLeak(unittest.TestCase):
    """Regression: column headers '1'/'2' must not leak into the 11 stats.
    Inter vs Udinese real card row: 71 20 9 51 32 17 90 68 45 49 51 -> over25=68."""

    NEW_LAYOUT = """ITALY - SERIE A
18:45
16
1
TIP
1
2026-09-14 18:45
-
Inter
-
Udinese
1
X
2
H1
HX
H2
1.5
2.5
3.5
BTS
OTS
71
20
9
51
32
17
90
68
45
49
51
your prediction
23
0
0
"""

    def test_stats_not_shifted(self):
        games = st.parse_card(self.NEW_LAYOUT)
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual(g["p_home"], 71)
        self.assertEqual(g["p_draw"], 20)
        self.assertEqual(g["p_away"], 9)
        self.assertEqual(g["over25"], 68)


class TestTeamToScoreMarkets(unittest.TestCase):
    def test_build_and_probs(self):
        from overunder.rules import market_probs
        prov = DemoProvider()
        fx = prov.fixtures()[0]
        for mkt in ("home_sc", "away_sc"):
            p = build_pick(fx, prov, market=mkt)
            self.assertEqual(p["market"], mkt)
            self.assertTrue(0.3 < p["confidence"] <= 0.98)
        strong = [M("H", 3, 1)] * 6
        weak = [M("A", 0, 2)] * 6
        probs = market_probs(strong, weak)
        self.assertGreater(probs["home_sc"], 0.9)
        self.assertLess(probs["away_sc"], 0.5)

    def test_settle_team_to_score(self):
        import tempfile, importlib
        os.environ["OU_DATA_DIR"] = tempfile.mkdtemp(prefix="ou_sc_")
        import overunder.config as cfg
        importlib.reload(cfg)
        importlib.reload(hist)
        prov = DemoProvider()
        fx = prov.fixtures()[0]
        hist.record_picks([build_pick(fx, prov, market="home_sc")])
        n = hist.settle([{"home": fx["home"], "away": fx["away"], "hg": 0, "ag": 3}])
        self.assertEqual(n, 1)
        s = hist.stats()
        self.assertEqual(list(s["overall"].values())[0]["l"], 1)


class TestHistoryDB(unittest.TestCase):
    def test_db_add_dedupes_and_merges(self):
        from overunder.providers import db_add_match, merge_history
        db = {}
        self.assertTrue(db_add_match(db, "St Gallen", "H", 3, 1, "2026-08-01"))
        self.assertFalse(db_add_match(db, "St Gallen", "H", 3, 1, "2026-08-01"))
        page = [{"venue": "H", "gf": 2, "ga": 0, "date": "2026-08-05"}]
        merged = merge_history(page, "St Gallen", db=db)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["date"], "2026-08-01")


class TestRulesVenueOverall(unittest.TestCase):
    def test_seventeen_checks(self):
        home = [M("H", 3, 1), M("H", 2, 2), M("H", 3, 0), M("A", 1, 1),
                M("H", 2, 1), M("A", 2, 2)]
        checks = run_checks(home, home)
        self.assertEqual(len(checks), 17)
        # strong scoring team at home: venue + overall checks pass together
        self.assertTrue(checks["H1"] and checks["H3"] and checks["H6"] and checks["H7"])
        # weak away scoring: away venue checks fail while overall may differ
        weak = [M("A", 0, 1), M("A", 1, 0), M("A", 0, 0), M("H", 0, 0),
                M("A", 0, 1), M("H", 0, 0)]
        c2 = run_checks(home, weak)
        self.assertFalse(c2["A1"] or c2["A3"])


class TestNoLookahead(unittest.TestCase):
    def test_merge_history_before_filter(self):
        from overunder.providers import merge_history
        db = {"leeds": [
            {"venue": "H", "gf": 3, "ga": 1, "date": "2026-08-01"},
            {"venue": "H", "gf": 4, "ga": 0, "date": "2026-09-05"},  # AFTER cutoff
        ]}
        merged = merge_history([], "Leeds", db=db, before="2026-09-01")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["date"], "2026-08-01")

    def test_build_pick_defaults_to_fixture_day(self):
        prov = DemoProvider()
        fx = prov.fixtures()[0]   # date 2026-09-12
        p = build_pick(fx, prov)  # before = fixture date -> demo Aug form only
        self.assertGreater(p["confidence"], 0.3)


class TestSoccerbaseParser(unittest.TestCase):
    SAMPLE_HTML = (
        '<table><tr><td><a href="/tournaments/tournament.sd?comp_id=1">Premier League</a></td></tr>'
        '<tr><td><a href="/matches/results.sd?date=2026-09-14">14/09/2026</a></td>'
        '<td><a href="/teams/team.sd?team_id=1420&teamTabs=results">Arsenal</a></td>'
        '<td><em>2 - 1</em></td>'
        '<td><a href="/teams/team.sd?team_id=1050&teamTabs=results">Chelsea</a></td></tr>'
        '<tr><td><a href="/matches/results.sd?date=2026-09-14">14/09/2026</a></td>'
        '<td><a href="/teams/team.sd?team_id=2001&teamTabs=results">Everton</a></td>'
        '<td>v</td>'
        '<td><a href="/teams/team.sd?team_id=2002&teamTabs=results">Leeds</a></td></tr>'
        "</table>")

    def test_parse_rows(self):
        from overunder.providers import SoccerbaseProvider
        prov = SoccerbaseProvider.__new__(SoccerbaseProvider)   # no network
        prov._ids = {}
        prov._save_ids = lambda: None
        rows = prov._parse_rows(self.SAMPLE_HTML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["home"], "Arsenal")
        self.assertEqual((rows[0]["hg"], rows[0]["ag"]), (2, 1))
        self.assertEqual(rows[0]["league"], "Premier League")
        self.assertIsNone(rows[1]["hg"])   # fixture without score

    def test_day_page_score_between_teams(self):
        """Day pages put the score BETWEEN the two team links."""
        from overunder.providers import SoccerbaseProvider
        prov = SoccerbaseProvider.__new__(SoccerbaseProvider)
        prov._ids = {}
        prov._save_ids = lambda: None
        html = ('<tr><td><a href="/tournaments/tournament.sd?comp_id=1">Premier League</a></td></tr>'
                '<tr><td><a href="/teams/team.sd?team_id=621">Coventry</a></td>'
                '<td><a href="match.sd?id=1"><u>0 - 5</u></a></td>'
                '<td><a href="/teams/team.sd?team_id=381">Brighton</a></td></tr>'
                # split spans, score between teams (day-page style):
                '<tr><td><a href="/teams/team.sd?team_id=1724">Man Utd</a></td>'
                '<td><span>1</span>-<span>2</span></td>'
                '<td><a href="/teams/team.sd?team_id=1718">Man City</a></td></tr>')
        rows = prov._parse_rows(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["hg"], rows[0]["ag"]), (0, 5))
        self.assertEqual((rows[1]["hg"], rows[1]["ag"]), (1, 2))

    def test_unlinked_league_header(self):
        from overunder.providers import SoccerbaseProvider
        prov = SoccerbaseProvider.__new__(SoccerbaseProvider)
        prov._ids = {}
        prov._save_ids = lambda: None
        html = ('<tr><td><a href="/tournaments/tournament.sd?comp_id=127">Croatian HNL</a></td></tr>'
                '<tr><td colspan="6">Venezuela Primera Clausura</td></tr>'
                '<tr><td><a href="/teams/team.sd?team_id=1">Caracas</a></td>'
                '<td>2 - 0</td>'
                '<td><a href="/teams/team.sd?team_id=2">Monagas</a></td></tr>')
        rows = prov._parse_rows(html)
        self.assertEqual(rows[0]["league"], "Venezuela Primera Clausura")


class TestCorruptHistory(unittest.TestCase):
    def test_empty_history_file_is_not_fatal(self):
        import tempfile, importlib
        d = tempfile.mkdtemp(prefix="ou_corrupt_")
        os.environ["OU_DATA_DIR"] = d
        import overunder.config as cfg
        importlib.reload(cfg)
        importlib.reload(hist)
        os.makedirs(d, exist_ok=True)
        open(cfg.HISTORY_FILE, "w").close()   # 0-byte file, as after manual deletion
        s = hist.stats()                       # must not raise
        self.assertEqual(s["settled_total"], 0)
        self.assertEqual(hist.record_picks([]), 0)
        # and a corrupt (non-json) file gets quarantined, not fatal
        with open(cfg.HISTORY_FILE, "w") as f:
            f.write("{not json")
        s = hist.stats()
        self.assertEqual(s["settled_total"], 0)
        self.assertTrue(any(".corrupt-" in fn for fn in os.listdir(d)))


class TestMultiDay(unittest.TestCase):
    def test_settle_auto_scans_pending_dates(self):
        import tempfile, importlib
        os.environ["OU_DATA_DIR"] = tempfile.mkdtemp(prefix="ou_md_")
        import overunder.config as cfg
        importlib.reload(cfg)
        importlib.reload(hist)
        prov = DemoProvider()
        fx = prov.fixtures()[:2]
        p1 = build_pick(fx[0], prov)
        p2 = build_pick(fx[1], prov)
        p1["date"] = "2026-09-12"
        p2["date"] = "2026-09-13"     # different day, same results source
        hist.record_picks([p1, p2])
        h = hist._load()
        self.assertEqual(len(h["pending"]), 2)
        # emulate `settle` with no --date: one pass per pending date
        for d in sorted({r["date"] for r in h["pending"]}):
            hist.settle(prov.results(d))
        s = hist.stats()
        self.assertEqual(s["pending"], 0)
        self.assertEqual(s["settled_total"], 2)

    def test_predict_days_demo(self):
        import subprocess as sp
        import tempfile, importlib
        os.environ["OU_DATA_DIR"] = tempfile.mkdtemp(prefix="ou_pd_")
        import overunder.config as cfg
        importlib.reload(cfg)
        importlib.reload(hist)
        from overunder.cli import main
        main(["predict", "--demo", "--days", "3", "--date", "2026-09-12",
              "--markets", "over"])  # window starts on demo fixtures day
        s = hist.stats()
        self.assertGreaterEqual(s["pending"], 1)


class TestDotenv(unittest.TestCase):
    def test_env_file_loads(self):
        import tempfile
        from overunder.config import _load_dotenv
        d = tempfile.mkdtemp()
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("OU_CACHE_DIR=/tmp/ou_env_test\n")
        old = os.getcwd()
        os.chdir(d)
        try:
            _load_dotenv()
            self.assertEqual(os.environ.get("OU_CACHE_DIR"), "/tmp/ou_env_test")
        finally:
            os.chdir(old)
            os.environ.pop("OU_CACHE_DIR", None)


if __name__ == "__main__":
    unittest.main()
