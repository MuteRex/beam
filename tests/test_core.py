"""Tests for the non-UI core: validation, config, command lines, discovery parsing.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")

from beam import config, options, probe  # noqa: E402
from beam.launcher import MoonlightLauncher  # noqa: E402
from beam.providers.base import Host  # noqa: E402
from beam.providers.tailscale import TailscaleProvider  # noqa: E402


class ValidAddress(unittest.TestCase):
    def test_accepts_ips_and_names(self):
        for a in ("192.168.68.117", "100.64.25.30", "fd7a:115c:a1e0::1",
                  "simon-vivobook", "simon-vivobook.tail1234.ts.net", "host.local."):
            self.assertTrue(probe.valid_address(a), a)

    def test_rejects_options_urls_and_junk(self):
        for a in ("", "-oProxyCommand=x", "--help", "a b", "host/path", "http://x",
                  "x;rm", "a" * 300, None, 5, "[::1]", "host:47989"):
            self.assertFalse(probe.valid_address(a), a)


class Config(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.patches = [mock.patch.object(config, "CONFIG_DIR", d),
                        mock.patch.object(config, "CONFIG_PATH", d / "config.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.dir.cleanup()

    def test_wrong_types_fall_back_to_defaults(self):
        config.CONFIG_PATH.write_text(json.dumps(
            {"fps": "120; rm -rf ~", "vsync": 1, "bitrate": True, "provider": "local"}))
        c = config.load()
        self.assertEqual(c["fps"], config.DEFAULTS["fps"])
        self.assertEqual(c["vsync"], config.DEFAULTS["vsync"])
        self.assertEqual(c["bitrate"], config.DEFAULTS["bitrate"])
        self.assertEqual(c["provider"], "local")

    def test_non_dict_or_corrupt_file(self):
        for text in ("[1, 2]", "{not json", ""):
            config.CONFIG_PATH.write_text(text)
            self.assertEqual(config.load(), config.DEFAULTS)

    def test_save_round_trip_is_private(self):
        c = config.load()
        c["fps"] = 120
        c["unknown"] = "dropped"
        config.save(c)
        self.assertEqual(config.load()["fps"], 120)
        self.assertNotIn("unknown", json.loads(config.CONFIG_PATH.read_text()))
        self.assertEqual(os.stat(config.CONFIG_PATH).st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], ["config.json"])


class CommandLine(unittest.TestCase):
    def launcher(self, **overrides):
        c = dict(config.DEFAULTS, moonlight_bin="/bin/true", **overrides)
        return MoonlightLauncher(c)

    def test_host_values_follow_double_dash(self):
        args = self.launcher()._stream_args("192.168.1.5", "--quit-after")
        self.assertEqual(args[-3:], ["--", "192.168.1.5", "--quit-after"])

    def test_stream_rejects_bad_address(self):
        with self.assertRaises(ValueError):
            self.launcher().stream("-oX")

    def test_pair_and_list_reject_bad_address(self):
        launcher = self.launcher()
        self.assertFalse(launcher.pair("--help", "1234")[0])
        self.assertEqual(launcher.list_apps("--help"), [])

    def test_custom_resolution_and_fps(self):
        args = self.launcher(custom_resolution="2560x1080", custom_fps=100).video_args()
        self.assertEqual(args[args.index("--resolution") + 1], "2560x1080")
        self.assertEqual(args[args.index("--fps") + 1], "100")
        args = self.launcher(custom_resolution="bogus").video_args()
        self.assertEqual(args[args.index("--resolution") + 1], "1920x1080")

    def test_every_switch_is_explicit(self):
        args = options.cli_args(config.DEFAULTS)
        for o in options.ALL:
            if o.kind == "switch" and o.flag:
                self.assertTrue(f"--{o.flag}" in args or f"--no-{o.flag}" in args, o.key)

    def test_choice_outside_list_uses_default(self):
        args = options.cli_args(dict(config.DEFAULTS, capture_system_keys="; evil"))
        i = args.index("--capture-system-keys")
        self.assertEqual(args[i + 1], "fullscreen")

    def test_prefers_lan_route(self):
        h = Host("x", "x", "100.64.0.2", extra={"routes": [
            {"kind": "tailscale", "address": "100.64.0.2"},
            {"kind": "lan", "address": "192.168.1.9"}]})
        self.assertEqual(self.launcher().address_for(h), "192.168.1.9")
        self.assertEqual(self.launcher(prefer_lan=False).address_for(h), "100.64.0.2")


class Tailscale(unittest.TestCase):
    def test_peers_become_hosts_and_bad_addresses_are_dropped(self):
        status = {"Self": {"ID": "me"}, "Peer": {
            "a": {"ID": "a", "HostName": "laptop", "TailscaleIPs": ["100.64.0.2"],
                  "Online": True, "OS": "linux", "PublicKey": "k1"},
            "b": {"ID": "b", "HostName": "evil", "TailscaleIPs": ["-oProxyCommand=x"],
                  "Online": True},
            "c": {"ID": "c", "HostName": "localhost", "DNSName": "phone.tail.ts.net.",
                  "Online": False, "LastSeen": "0001-01-01T00:00:00Z"},
        }}
        p = TailscaleProvider()
        with mock.patch.object(p, "_status", return_value=status):
            hosts = p.list_hosts()
        self.assertEqual([h.name for h in hosts], ["laptop", "phone"])
        self.assertEqual(hosts[1].address, "phone.tail.ts.net")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/serverinfo":
            body = (b"<root><hostname>vivo &lt;b&gt;</hostname><uniqueid>ABC</uniqueid>"
                    b"<ServerCodecModeSupport>65793</ServerCodecModeSupport></root>")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body + b"x" * 200000)
        else:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/serverinfo")
            self.end_headers()

    def log_message(self, *_):
        pass


class ServerInfo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_parses_and_caps(self):
        with mock.patch.object(probe, "SERVERINFO_PORT", self.server.server_port):
            info = probe.server_info("127.0.0.1")
            self.assertEqual(info["uniqueid"], "ABC")
            self.assertEqual(probe.server_identity("127.0.0.1"), ("ABC", "vivo &lt;b&gt;"))

    def test_refuses_redirects(self):
        import urllib.error
        # Any other path on the test server answers with a redirect
        with self.assertRaises(urllib.error.HTTPError) as cm:
            probe._opener.open(f"http://127.0.0.1:{self.server.server_port}/other", timeout=2)
        self.assertEqual(cm.exception.code, 302)
        cm.exception.close()

    def test_bad_address_never_fetched(self):
        with mock.patch.object(probe._opener, "open") as spy:
            self.assertIsNone(probe.server_info("not a host"))
            spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
