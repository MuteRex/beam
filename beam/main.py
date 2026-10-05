"""Beam application entry point."""
from __future__ import annotations

import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from . import bench  # noqa: E402
from .window import BeamWindow  # noqa: E402

APP_ID = "dev.simon.Beam"


class BeamApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        self.set_accels_for_action("win.settings", ["<Control>comma"])
        win = self.props.active_window or BeamWindow(self)
        win.present()

    def do_shutdown(self):
        # Stop a connection test still running in the background
        bench.terminate_all()
        Adw.Application.do_shutdown(self)


def main() -> int:
    return BeamApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
