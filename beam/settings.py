"""Stream-preferences dialog (libadwaita preferences)."""
from __future__ import annotations

from gi.repository import Adw, Gtk

from . import config as cfg

RESOLUTIONS = ["1280x720", "1920x1080", "2560x1440", "3840x2160"]
FPS = ["30", "60", "90", "120"]
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

        page = Adw.PreferencesPage(icon_name="preferences-system-symbolic")
        self.add(page)

        video = Adw.PreferencesGroup(title="Video")
        page.add(video)

        self.res = _combo(RESOLUTIONS, self.config.get("resolution"))
        self._row(video, "Resolution", self.res)

        self.fps = _combo(FPS, str(self.config.get("fps")))
        self._row(video, "Frame rate (FPS)", self.fps)

        self.bitrate = Adw.SpinRow(
            title="Bitrate (Mbps, 0 = auto)",
            adjustment=Gtk.Adjustment(
                lower=0, upper=150, step_increment=5,
                value=int(self.config.get("bitrate", 0)) / 1000))
        video.add(self.bitrate)

        self.display = _combo(DISPLAY, self.config.get("display_mode"))
        self._row(video, "Display mode", self.display)

        audio = Adw.PreferencesGroup(title="Audio & input")
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

        self.connect("closed", self._save)

    def _row(self, group, title, widget):
        r = Adw.ActionRow(title=title)
        r.add_suffix(widget)
        group.add(r)

    def _save(self, *_):
        self.config["resolution"] = RESOLUTIONS[self.res.get_selected()]
        self.config["fps"] = int(FPS[self.fps.get_selected()])
        self.config["bitrate"] = int(self.bitrate.get_value() * 1000)
        self.config["display_mode"] = DISPLAY[self.display.get_selected()]
        self.config["audio_config"] = AUDIO[self.audio.get_selected()]
        self.config["multi_controller"] = self.multi.get_active()
        self.config["default_app"] = self.app.get_text().strip() or "Desktop"
        cfg.save(self.config)
        self.window.launcher.config = self.config
