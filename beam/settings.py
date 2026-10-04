"""Stream-preferences dialog (libadwaita preferences)."""
from __future__ import annotations

from gi.repository import Adw, Gtk

from . import config as cfg
from . import options
from .launcher import is_fork, resolve_moonlight_bin

RESOLUTIONS = ["1280x720", "1920x1080", "2560x1440", "3840x2160"]
FPS = ["30", "60", "75", "90", "100", "120", "144", "165"]
CODECS = ["auto", "H.264", "HEVC", "AV1"]
DECODERS = ["auto", "hardware", "software"]
DISPLAY = ["fullscreen", "borderless", "windowed"]
AUDIO = ["stereo", "5.1-surround", "7.1-surround"]


def _combo(strings, current):
    d = Gtk.DropDown.new_from_strings(strings)
    if current in strings:
        d.set_selected(strings.index(current))
    d.set_valign(Gtk.Align.CENTER)
    return d


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, window):
        super().__init__(title="Stream settings")
        self.window = window
        self.config = window.config

        page = Adw.PreferencesPage(title="General",
                                   icon_name="preferences-system-symbolic")
        self.add(page)

        video = Adw.PreferencesGroup(title="Video")
        page.add(video)

        self.res = _combo(RESOLUTIONS, self.config.get("resolution"))
        self._row(video, "Resolution", self.res)

        self.fps = _combo(FPS, str(self.config.get("fps")))
        fps_row = self._row(video, "Frame rate (FPS)", self.fps)
        custom_fps = int(self.config.get("custom_fps") or 0)
        if custom_fps > 0:
            fps_row.set_subtitle(f"Overridden by Advanced → Custom frame rate ({custom_fps})")

        self.bitrate = Adw.SpinRow(
            title="Bitrate (Mbps, 0 = auto)",
            adjustment=Gtk.Adjustment(
                lower=0, upper=150, step_increment=5,
                value=int(self.config.get("bitrate", 0)) / 1000))
        video.add(self.bitrate)

        self.display = _combo(DISPLAY, self.config.get("display_mode"))
        self._row(video, "Display mode", self.display)

        latency = Adw.PreferencesGroup(
            title="Latency",
            description="Defaults are tuned for the lowest delay. Use “Test "
                        "connection” on a host card to measure the effect.")
        page.add(latency)
        self.codec = _combo(CODECS, self.config.get("video_codec", "auto"))
        self._row(latency, "Video codec", self.codec)
        self.decoder = _combo(DECODERS, self.config.get("video_decoder", "auto"))
        self._row(latency, "Video decoder", self.decoder)
        self.vsync = Adw.SwitchRow(
            title="V-Sync",
            subtitle="Off is fastest; on removes tearing but can add a frame",
            active=bool(self.config.get("vsync")))
        latency.add(self.vsync)
        self.pacing = Adw.SwitchRow(
            title="Frame pacing",
            subtitle="Smoother motion at the cost of up to one frame of delay",
            active=bool(self.config.get("frame_pacing")))
        latency.add(self.pacing)
        self.lan = Adw.SwitchRow(
            title="Prefer LAN connection",
            subtitle="Skip the Tailscale tunnel when the host is on this network",
            active=bool(self.config.get("prefer_lan", True)))
        latency.add(self.lan)
        self.overlay = Adw.SwitchRow(
            title="Performance stats in stream",
            subtitle="Latency breakdown overlay (also in the Beam menu)",
            active=bool(self.config.get("performance_overlay")))
        latency.add(self.overlay)

        audio = Adw.PreferencesGroup(title="Audio &amp; input")
        page.add(audio)
        self.audio = _combo(AUDIO, self.config.get("audio_config"))
        self._row(audio, "Audio", self.audio)
        self.multi = Adw.SwitchRow(title="Multiple controllers",
                                   active=bool(self.config.get("multi_controller")))
        audio.add(self.multi)

        apps = Adw.PreferencesGroup(title="Default app")
        page.add(apps)
        self.app = Adw.EntryRow(title="App name")
        self.app.set_text(self.config.get("default_app", "Desktop"))
        apps.add(self.app)

        advanced = self._build_advanced_page()

        client = Adw.PreferencesGroup(
            title="Moonlight client",
            description="Leave the path empty to use the Beam fork when it is "
                        "built, otherwise the system Moonlight.")
        advanced.add(client)
        self.bin = Adw.EntryRow(title="Moonlight binary (empty = auto)")
        self.bin.set_text(self.config.get("moonlight_bin", ""))
        self.bin.connect("changed", self._update_bin_status)
        client.add(self.bin)
        self.bin_status = Adw.ActionRow(title="In use")
        self.bin_status.add_css_class("property")
        client.add(self.bin_status)
        self.pill = Adw.SwitchRow(
            title="In-stream Beam button",
            subtitle="Clickable menu at the top of the stream "
                     "(Ctrl+Alt+Shift+B opens it either way)",
            active=bool(self.config.get("show_pill", True)))
        client.add(self.pill)
        self._update_bin_status()
        advanced.add(self._reset_group)

        self.connect("closed", self._save)

    def _update_bin_status(self, *_):
        path = resolve_moonlight_bin(self.bin.get_text())
        self.bin_status.set_subtitle(path)
        self.pill.set_sensitive(is_fork(path))

    # ---- Advanced page ------------------------------------------------
    def _build_advanced_page(self):
        page = Adw.PreferencesPage(title="Advanced",
                                   icon_name="applications-engineering-symbolic")
        self.add(page)
        self.advanced_page = page
        self.adv = {}

        for title, opts in options.ADVANCED:
            group = Adw.PreferencesGroup(title=title)
            page.add(group)
            for o in opts:
                group.add(self._option_row(o))

        reset_group = Adw.PreferencesGroup()
        reset = Adw.ButtonRow(title="Reset advanced settings")
        reset.add_css_class("destructive-action")
        reset.connect("activated", self._reset_advanced)
        reset_group.add(reset)
        self._reset_group = reset_group
        return page

    def _option_row(self, o):
        value = self.config.get(o.key, o.default)
        if o.kind == "switch":
            row = Adw.SwitchRow(title=o.title, subtitle=o.subtitle, active=bool(value))
        elif o.kind == "choice":
            row = Adw.ComboRow(title=o.title, subtitle=o.subtitle,
                               model=Gtk.StringList.new(list(o.choices)))
            row.set_selected(o.choices.index(value) if value in o.choices
                             else o.choices.index(o.default))
        elif o.kind == "spin":
            row = Adw.SpinRow(title=o.title, subtitle=o.subtitle,
                              adjustment=Gtk.Adjustment(lower=o.low, upper=o.high,
                                                        step_increment=o.step,
                                                        value=int(value or 0)))
        else:
            row = Adw.EntryRow(title=f"{o.title} — {o.subtitle}" if o.subtitle else o.title)
            row.set_text(str(value or ""))
            if o.key == "custom_resolution":
                row.connect("changed", self._check_resolution)
        self.adv[o.key] = row
        return row

    def _check_resolution(self, row):
        text = row.get_text().strip()
        if text and not options.valid_resolution(text):
            row.add_css_class("error")
        else:
            row.remove_css_class("error")

    def _option_value(self, o):
        row = self.adv[o.key]
        if o.kind == "switch":
            return row.get_active()
        if o.kind == "choice":
            return o.choices[row.get_selected()]
        if o.kind == "spin":
            return int(row.get_value())
        text = row.get_text().strip()
        if o.key == "custom_resolution" and not options.valid_resolution(text):
            return ""
        return text

    def _reset_advanced(self, *_):
        for o in options.ALL:
            row = self.adv[o.key]
            if o.kind == "switch":
                row.set_active(bool(o.default))
            elif o.kind == "choice":
                row.set_selected(o.choices.index(o.default))
            elif o.kind == "spin":
                row.set_value(int(o.default))
            else:
                row.set_text(str(o.default))
        self.add_toast(Adw.Toast.new("Advanced settings reset to defaults"))

    def _row(self, group, title, widget):
        r = Adw.ActionRow(title=title)
        r.add_suffix(widget)
        group.add(r)
        return r

    def _save(self, *_):
        self.config["resolution"] = RESOLUTIONS[self.res.get_selected()]
        self.config["fps"] = int(FPS[self.fps.get_selected()])
        self.config["bitrate"] = int(self.bitrate.get_value() * 1000)
        self.config["display_mode"] = DISPLAY[self.display.get_selected()]
        self.config["audio_config"] = AUDIO[self.audio.get_selected()]
        self.config["multi_controller"] = self.multi.get_active()
        self.config["default_app"] = self.app.get_text().strip() or "Desktop"
        self.config["video_codec"] = CODECS[self.codec.get_selected()]
        self.config["video_decoder"] = DECODERS[self.decoder.get_selected()]
        self.config["vsync"] = self.vsync.get_active()
        self.config["frame_pacing"] = self.pacing.get_active()
        self.config["prefer_lan"] = self.lan.get_active()
        self.config["performance_overlay"] = self.overlay.get_active()
        self.config["moonlight_bin"] = self.bin.get_text().strip()
        for o in options.ALL:
            self.config[o.key] = self._option_value(o)
        self.config["show_pill"] = self.pill.get_active()
        cfg.save(self.config)
        self.window.launcher.config = self.config
