"""Tests for bitrate choices and the Test connection logic (no display, no network).

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")

from beam import bench, bitrate, config, diagnose  # noqa: E402
from beam.diagnose import BAD, GOOD, OK, Step  # noqa: E402
from beam.launcher import MoonlightLauncher  # noqa: E402


class SliderSteps(unittest.TestCase):
    def test_round_trip_every_step(self):
        for i, kbps in enumerate(bitrate.STEPS_KBPS):
            self.assertEqual(bitrate.index_for(kbps), i)
            self.assertEqual(bitrate.kbps_at(i), kbps)

    def test_snaps_to_nearest(self):
        self.assertEqual(bitrate.kbps_at(bitrate.index_for(14988)), 15000)
        self.assertEqual(bitrate.kbps_at(bitrate.index_for(7000)), 6000)   # tie → lower
        self.assertEqual(bitrate.kbps_at(bitrate.index_for(999999)), bitrate.MAX_KBPS)
        self.assertEqual(bitrate.index_for(0), 0)
        self.assertEqual(bitrate.index_for(-5), 0)

    def test_out_of_range_index_clamped(self):
        self.assertEqual(bitrate.kbps_at(-3), 0)
        self.assertEqual(bitrate.kbps_at(500), bitrate.MAX_KBPS)

    def test_steps_ascend(self):
        self.assertEqual(bitrate.STEPS_KBPS, sorted(set(bitrate.STEPS_KBPS)))

    def test_labels_and_usage(self):
        self.assertEqual(bitrate.label(0), "Auto")
        self.assertEqual(bitrate.label(0, "No limit"), "No limit")
        self.assertEqual(bitrate.label(20000), "20 Mbps")
        self.assertEqual(bitrate.label(2500), "2.5 Mbps")
        self.assertAlmostEqual(bitrate.gb_per_hour(8000), 3.6)
        self.assertEqual(bitrate.usage_hint(8000), "about 3.6 GB an hour")
        self.assertEqual(bitrate.usage_hint(50000), "about 22 GB an hour")
        self.assertEqual(bitrate.usage_hint(0), "")


class Choose(unittest.TestCase):
    def conf(self, **kw):
        return dict(config.DEFAULTS, **kw)

    def test_home_uses_home_setting(self):
        self.assertEqual(bitrate.choose(self.conf(), "home"), 0)
        self.assertEqual(bitrate.choose(self.conf(bitrate=40000), "home"), 40000)

    def test_away_cap(self):
        self.assertEqual(bitrate.choose(self.conf(), "away"), 8000)
        self.assertEqual(bitrate.choose(self.conf(bitrate=40000), "away"), 8000)
        self.assertEqual(bitrate.choose(self.conf(bitrate=5000), "away"), 5000)
        self.assertEqual(bitrate.choose(self.conf(away_bitrate=0, bitrate=30000), "away"), 30000)

    def test_tested_value_wins_on_its_route_only(self):
        c = self.conf(bitrate=40000, host_bitrates={"pc": {"name": "pc", "away": 12000}})
        self.assertEqual(bitrate.choose(c, "away", "pc"), 12000)   # above the 8 Mbps cap
        self.assertEqual(bitrate.choose(c, "home", "pc"), 40000)   # no home value saved
        self.assertEqual(bitrate.choose(c, "away", "other"), 8000)
        self.assertEqual(bitrate.choose(c, "away", None), 8000)

    def test_metered_caps_every_route(self):
        c = self.conf(bitrate=40000, host_bitrates={"pc": {"name": "pc", "away": 12000,
                                                           "home": 60000}})
        self.assertEqual(bitrate.choose(c, "home", None, metered=True), 8000)
        self.assertEqual(bitrate.choose(c, "home", "pc", metered=True), 8000)  # tested too
        self.assertEqual(bitrate.choose(c, "away", "pc", metered=True), 8000)
        self.assertEqual(bitrate.choose(self.conf(), "home", metered=True), 8000)  # auto
        self.assertEqual(bitrate.choose(self.conf(bitrate=5000), "home", metered=True), 5000)
        self.assertEqual(bitrate.choose(self.conf(away_bitrate=0, bitrate=40000), "home",
                                        metered=True), 40000)  # no cap set

    def test_bad_saved_values_ignored(self):
        for bad in (True, "12000", -5, 0, None):
            c = self.conf(host_bitrates={"pc": {"away": bad}})
            self.assertEqual(bitrate.host_limit(c, "pc", "away"), 0, bad)


class LauncherUsesHostKey(unittest.TestCase):
    def test_stream_args(self):
        c = dict(config.DEFAULTS, host_bitrates={"pc": {"name": "pc", "away": 12000, "home": 60000}})
        launcher = MoonlightLauncher(c)
        with mock.patch.object(MoonlightLauncher, "bin", new_callable=mock.PropertyMock,
                               return_value="/usr/bin/moonlight"), \
                mock.patch("beam.probe.network_metered", return_value=False):
            away = launcher._stream_args("100.64.25.30", "Desktop", "pc")
            home = launcher._stream_args("192.168.68.210", "Desktop", "pc")
        self.assertEqual(away[away.index("--bitrate") + 1], "12000")
        self.assertEqual(home[home.index("--bitrate") + 1], "60000")


class HostBitratesConfig(unittest.TestCase):
    def test_coerce_keeps_valid_drops_junk(self):
        raw = {
            "pc": {"name": "simon-gaming-pc", "away": 12000, "home": 60000},
            "half": {"name": "x", "away": 5000, "home": "lots"},
            "none": {"name": "y"},
            "bool": {"away": True},
            "huge": {"away": 10**9},
            5: {"away": 1000},
            "notdict": [1, 2],
        }
        clean = config._coerce("host_bitrates", raw)
        self.assertEqual(clean["pc"], {"name": "simon-gaming-pc", "away": 12000, "home": 60000})
        self.assertEqual(clean["half"], {"name": "x", "away": 5000})
        for gone in ("none", "bool", "huge", 5, "notdict"):
            self.assertNotIn(gone, clean)
        self.assertEqual(config._coerce("host_bitrates", "junk"), {})


class Ladder(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(diagnose.ladder_for("home"), diagnose.HOME_LADDER)
        self.assertEqual(diagnose.ladder_for("away"), diagnose.AWAY_LADDER)
        for ladder in (diagnose.HOME_LADDER, diagnose.AWAY_LADDER):
            self.assertEqual(ladder, sorted(ladder))
        # A copy: callers can't change the module's ladder
        diagnose.ladder_for("home").append(1)
        self.assertNotIn(1, diagnose.HOME_LADDER)

    def test_estimate(self):
        seconds, mb = diagnose.estimate("away", 5)
        self.assertEqual(mb, sum(diagnose.AWAY_LADDER) * 1000 / 8 * 8 / 1e6)
        self.assertGreater(seconds, 5 * len(diagnose.AWAY_LADDER))
        self.assertLess(diagnose.estimate("away", 5)[1], diagnose.estimate("home", 5)[1])

    def test_rate_step(self):
        self.assertEqual(rate({"net_drop_pct": 0.0}), GOOD)
        self.assertEqual(rate({"net_drop_pct": 0.6, "jitter_drop_pct": 0.4}), GOOD)
        self.assertEqual(rate({"net_drop_pct": 2.0}), OK)
        self.assertEqual(rate({"net_drop_pct": 3.5}), BAD)
        self.assertEqual(rate({}), BAD)
        self.assertEqual(rate({"net_drop_pct": 0}, "no stats logged"), BAD)

    def test_with_bitrate_replaces(self):
        args = ["--fps", "60", "--bitrate", "20000", "--no-vsync"]
        self.assertEqual(diagnose._with_bitrate(args, 5000),
                         ["--fps", "60", "--no-vsync", "--bitrate", "5000"])
        self.assertEqual(diagnose._with_bitrate([], 3000), ["--bitrate", "3000"])


def rate(stats, error=""):
    return diagnose.rate_step(stats, error)


def steps(*pairs):
    return [Step(k, r) for k, r in pairs]


class Recommend(unittest.TestCase):
    def test_headroom_below_last_clean(self):
        s = steps((3000, GOOD), (6000, GOOD), (10000, GOOD), (15000, BAD), (25000, ""))
        self.assertEqual(diagnose.recommend(s), 8000)

    def test_all_clean_to_the_top(self):
        s = steps(*[(k, GOOD) for k in diagnose.HOME_LADDER])
        self.assertEqual(diagnose.recommend(s), diagnose.HOME_LADDER[-1])

    def test_stopped_early_is_not_all_clean(self):
        # Stop pressed after two clean steps: still leaves headroom
        s = steps((3000, GOOD), (6000, GOOD), (10000, ""), (15000, ""), (25000, ""))
        self.assertEqual(diagnose.recommend(s), 5000)

    def test_only_marginal(self):
        s = steps((3000, OK), (6000, BAD), (10000, ""))
        self.assertEqual(diagnose.recommend(s), 1000)

    def test_marginal_above_clean(self):
        s = steps((3000, GOOD), (6000, OK), (10000, BAD))
        self.assertEqual(diagnose.recommend(s), 2000)

    def test_nothing_usable(self):
        self.assertIsNone(diagnose.recommend(steps((3000, BAD), (6000, ""))))
        self.assertIsNone(diagnose.recommend([]))

    def test_whole_mbps(self):
        s = steps((35000, GOOD), (50000, BAD))
        self.assertEqual(diagnose.recommend(s) % 1000, 0)


class Verdict(unittest.TestCase):
    def test_words(self):
        self.assertEqual(diagnose.verdict(80000, 0.5, 0, "home"), ("Excellent", GOOD))
        self.assertEqual(diagnose.verdict(20000, 0.5, 0, "home"), ("Good", GOOD))
        self.assertEqual(diagnose.verdict(8000, 0.5, 0, "home"), ("Usable", OK))
        self.assertEqual(diagnose.verdict(15000, 40, 0, "away"), ("Excellent", GOOD))
        self.assertEqual(diagnose.verdict(8000, 49, 0, "away"), ("Good", GOOD))
        self.assertEqual(diagnose.verdict(2000, 49, 0, "away"), ("Poor", BAD))
        self.assertEqual(diagnose.verdict(None, 1, 0, "home"), ("Poor", BAD))

    def test_loss_and_slow_ping_hold_it_back(self):
        self.assertEqual(diagnose.verdict(80000, 0.5, 5, "home")[0], "Usable")
        self.assertEqual(diagnose.verdict(25000, 120, 0, "away")[0], "Good")


class FakeLauncher:
    """Just enough of MoonlightLauncher for diagnose.run."""
    bin = "/usr/bin/moonlight"

    def __init__(self):
        self.config = dict(config.DEFAULTS)
        self.ended = []

    def video_args(self):
        return ["--fps", "60"]

    def host_busy(self, address):
        return True

    def end_session(self, address):
        self.ended.append(address)


class FakeCompositor:
    def __init__(self, *_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def fake_case(drops_by_kbps, calls):
    """bench.run_case stand-in: frames dropped per bitrate."""
    def run_case(binary, host, app, case, seconds, comp):
        kbps = int(case.args[case.args.index("--bitrate") + 1])
        calls.append(kbps)
        drop = drops_by_kbps.get(kbps, 50.0)
        stats = {"net_drop_pct": drop, "jitter_drop_pct": 0.0, "net_ms": 48, "net_var_ms": 6,
                 "host_ms": 3.9, "host_max_ms": 30, "decode_ms": 3.1, "queue_ms": 0.4,
                 "render_ms": 1.8, "net_fps": 60}
        return bench.Result(case, stats, "HEVC")
    return run_case


class RunTest(unittest.TestCase):
    """The whole test with the network and Moonlight replaced."""

    def run_test(self, drops, address="100.64.25.30", stop=None):
        calls, progress = [], []
        ping = (49.0, 7.0, 0.0) if address.startswith("100.") else (0.8, 0.2, 0.0)
        patches = [
            mock.patch.object(diagnose, "_ping", return_value=ping),
            mock.patch.object(diagnose, "_host_codecs", return_value={"H.264", "HEVC", "AV1"}),
            mock.patch.object(bench, "HeadlessCompositor", FakeCompositor),
            mock.patch.object(bench, "run_case", fake_case(drops, calls)),
        ]
        for p in patches:
            p.start()
        try:
            launcher = FakeLauncher()
            report = diagnose.run(launcher, address, "Desktop", step_seconds=1,
                                  progress=progress.append, stop=stop)
        finally:
            for p in patches:
                p.stop()
        return report, calls, progress, launcher

    def test_stops_at_first_bad_step(self):
        report, calls, progress, launcher = self.run_test({3000: 0, 6000: 0.2, 10000: 0.9, 15000: 9})
        self.assertEqual(calls, [3000, 6000, 10000, 15000])          # 25 never tried
        self.assertEqual([s.rating for s in report.steps], [GOOD, GOOD, GOOD, BAD, ""])
        self.assertEqual(report.recommended_kbps, 8000)
        self.assertEqual(report.route, "away")
        self.assertEqual((report.verdict, report.verdict_rating), ("Good", GOOD))
        self.assertEqual(launcher.ended, ["100.64.25.30"])           # Desktop session ended
        self.assertFalse(report.error)
        self.assertTrue(any(m.label == "Host encode" for m in report.metrics))

    def test_progress_is_monotonic_and_finishes(self):
        _r, _c, progress, _l = self.run_test({3000: 0, 6000: 0, 10000: 0, 15000: 0, 25000: 0})
        fractions = [p.fraction for p in progress]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        self.assertTrue(all(0 <= f <= 1 for f in fractions))
        # The chart sees every step get its rating as it happens
        rated = [sum(1 for s in p.steps if s.rating) for p in progress]
        self.assertEqual(rated, sorted(rated))
        self.assertEqual(rated[-1], 5)

    def test_all_clean_recommends_top(self):
        report, calls, _p, _l = self.run_test({k: 0 for k in diagnose.HOME_LADDER},
                                              address="192.168.68.210")
        self.assertEqual(report.route, "home")
        self.assertEqual(calls, diagnose.HOME_LADDER)
        self.assertEqual(report.recommended_kbps, diagnose.HOME_LADDER[-1])
        self.assertEqual(report.verdict, "Excellent")

    def test_lowest_step_fails(self):
        report, calls, _p, _l = self.run_test({3000: 40})
        self.assertEqual(calls, [3000])
        self.assertIsNone(report.recommended_kbps)
        self.assertEqual(report.verdict, "Poor")
        self.assertIn("too unsteady", report.error)

    def test_stop_ends_after_current_step(self):
        stop = threading.Event()
        calls_seen = []

        def stopping_case(binary, host, app, case, seconds, comp):
            calls_seen.append(case)
            stop.set()  # pressed while the first step streams
            return bench.Result(case, {"net_drop_pct": 0.0, "net_fps": 60}, "HEVC")

        with mock.patch.object(diagnose, "_ping", return_value=None), \
                mock.patch.object(diagnose, "_host_codecs", return_value=None), \
                mock.patch.object(bench, "HeadlessCompositor", FakeCompositor), \
                mock.patch.object(bench, "run_case", stopping_case):
            report = diagnose.run(FakeLauncher(), "100.64.25.30", step_seconds=1, stop=stop)
        self.assertEqual(len(calls_seen), 1)
        self.assertEqual(report.steps[0].rating, GOOD)
        self.assertEqual(report.recommended_kbps, 2000)   # 85% of 3 Mbps, whole Mbps

    def test_compositor_failure_reported(self):
        class Broken(FakeCompositor):
            def __enter__(self):
                raise RuntimeError("headless weston did not start (is weston installed?)")
        with mock.patch.object(diagnose, "_ping", return_value=None), \
                mock.patch.object(diagnose, "_host_codecs", return_value=None), \
                mock.patch.object(bench, "HeadlessCompositor", Broken):
            report = diagnose.run(FakeLauncher(), "192.168.68.210", step_seconds=1)
        self.assertIn("weston", report.error)


if __name__ == "__main__":
    unittest.main()
