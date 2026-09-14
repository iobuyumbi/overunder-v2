import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from overunder.rules import poisson_over25, run_checks
from overunder.teams import normalize, find_match
from overunder import statarea as st
from overunder.providers import DemoProvider
from overunder.predict import build_pick
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
