"""Beam main window — a Parsec-style grid of connectable machines."""
from __future__ import annotations

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib, Gio  # noqa: E402

from . import config as cfg  # noqa: E402
from . import probe  # noqa: E402
from .launcher import MoonlightLauncher  # noqa: E402
from .providers import ALL_PROVIDERS, Host  # noqa: E402

OS_ICON = {
    "linux": "computer-symbolic",
    "windows": "computer-symbolic",
    "macos": "computer-symbolic",
    "ios": "phone-symbolic",
    "android": "phone-symbolic",
    "": "network-server-symbolic",
}

# Parsec-ish: near-black canvas, dark cards, lime accent.
CSS = b"""
.beam-canvas { background: #0f0f0f; }
.beam-logo { font-weight: 800; font-size: 1.15rem; letter-spacing: 1px; }
.beam-logo-accent { color: #9ae600; }

.host-card {
  background: #1b1b1b;
  border-radius: 14px;
  border: 1px solid #262626;
  min-width: 210px;
}
.host-card:hover { border-color: #9ae600; }

.card-art {
  min-height: 118px;
  border-radius: 14px 14px 0 0;
  background: linear-gradient(135deg, #243018 0%, #171717 70%);
}
.card-art.offline { background: linear-gradient(135deg, #222 0%, #171717 70%); }
.card-art-icon { -gtk-icon-size: 52px; color: #9ae600; opacity: 0.9; }
.card-art.offline .card-art-icon { color: #666; }

.card-body { padding: 12px 14px 14px 14px; }
.host-name { font-weight: 700; font-size: 1.02rem; }

.status-dot { min-width: 9px; min-height: 9px; border-radius: 9px; }
.status-dot.online  { background: #9ae600; }
.status-dot.offline { background: #5a5a5a; }

.beam-connect {
  background: #9ae600; color: #0c0c0c; font-weight: 700;
  border-radius: 9px;
}
.beam-connect:hover { background: #aef31a; }
.beam-connect:disabled { background: #2a2a2a; color: #777; }

.pill-btn { border-radius: 999px; padding: 3px; }

.diag-good { color: #9ae600; font-weight: 600; }
.diag-ok { color: #f5c211; font-weight: 600; }
.diag-bad { color: #ff6b6b; font-weight: 600; }
"""


class HostCard(Gtk.Box):
    """One machine as a Parsec-like card: art header + name + connect."""

    def __init__(self, host: Host, window: "BeamWindow"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.host = host
        self.window = window
        self.add_css_class("host-card")

        # art header
        art = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        art.add_css_class("card-art")
        if not host.online:
            art.add_css_class("offline")
        icon = Gtk.Image.new_from_icon_name(OS_ICON.get(host.os, OS_ICON[""]))
        icon.add_css_class("card-art-icon")
        icon.set_hexpand(True)
        icon.set_vexpand(True)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        art.append(icon)
        self.append(art)

        # body
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.add_css_class("card-body")
        self.append(body)

        name = Gtk.Label(label=host.name, halign=Gtk.Align.START, xalign=0)
        name.add_css_class("host-name")
        name.set_ellipsize(3)
        body.append(name)

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                         halign=Gtk.Align.START)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("status-dot")
        dot.add_css_class("online" if host.online else "offline")
        status.append(dot)
        slabel = Gtk.Label(label=host.detail or host.address)
        slabel.add_css_class("dim-label")
        slabel.add_css_class("caption")
        status.append(slabel)
        body.append(status)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        connect = Gtk.Button(label="Connect", hexpand=True)
        connect.add_css_class("beam-connect")
        connect.set_sensitive(host.online)
        connect.connect("clicked", lambda *_: window.on_connect(host))
        row.append(connect)

        menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic")
        menu_btn.add_css_class("flat")
        m = Gio.Menu()
        m.append("Pair with host…", f"win.pair::{host.id}")
        m.append("Choose app…", f"win.apps::{host.id}")
        m.append("Test connection…", f"win.test::{host.id}")
        menu_btn.set_menu_model(m)
        row.append(menu_btn)
        body.append(row)


class BeamWindow(Adw.ApplicationWindow):
    def _monitor_pos(self):
        """Layout position of the monitor Beam is on, so the stream opens there."""
        surface = self.get_surface()
        if surface is None:
            return None
        monitor = self.get_display().get_monitor_at_surface(surface)
        if monitor is None:
            return None
        g = monitor.get_geometry()
        return (g.x, g.y)

    def __init__(self, app):
        super().__init__(application=app, title="Beam")
        self.set_default_size(820, 580)
        self.config = cfg.load()
        self.launcher = MoonlightLauncher(self.config)
        self.providers = {p.id: p() for p in ALL_PROVIDERS}
        self._hosts_by_id: dict[str, Host] = {}
        self._all_hosts: list[Host] = []

        # force dark, Parsec-like
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK)

        self._install_css()
        self._build_ui()
        self._install_actions()
        self.refresh()

    # ---- chrome ---------------------------------------------------------
    def _install_css(self):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), prov,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build_ui(self):
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        toolbar = Adw.ToolbarView()
        toolbar.add_css_class("beam-canvas")
        self.toasts.set_child(toolbar)

        header = Adw.HeaderBar()
        header.add_css_class("beam-canvas")
        toolbar.add_top_bar(header)

        # logo (left)
        logo = Gtk.Label(use_markup=True,
                         label='<span>BEAM</span>')
        logo.set_markup('BE<span foreground="#9ae600">AM</span>')
        logo.add_css_class("beam-logo")
        header.pack_start(logo)

        # provider switcher
        self.provider_ids = list(self.providers.keys())
        self.provider_drop = Gtk.DropDown.new_from_strings(
            [p.label for p in self.providers.values()])
        start = self.config.get("provider", "tailscale")
        if start in self.provider_ids:
            self.provider_drop.set_selected(self.provider_ids.index(start))
        self.provider_drop.connect("notify::selected", self._on_provider_changed)
        header.pack_start(self.provider_drop)

        # fullscreen / windowed toggle (center-right)
        self.mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.mode_box.add_css_class("linked")
        self._fs_btn = Gtk.ToggleButton(label="Fullscreen")
        self._win_btn = Gtk.ToggleButton(label="Windowed")
        self._win_btn.set_group(self._fs_btn)
        current = self.config.get("display_mode", "fullscreen")
        (self._win_btn if current == "windowed" else self._fs_btn).set_active(True)
        self._fs_btn.connect("toggled", self._on_mode_toggled)
        self.mode_box.append(self._fs_btn)
        self.mode_box.append(self._win_btn)
        header.pack_end(self._pill_menu_button())
        header.pack_end(self.mode_box)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic",
                             tooltip_text="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)

        # body stack
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self.stack)

        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.flow = Gtk.FlowBox(
            valign=Gtk.Align.START, max_children_per_line=4,
            min_children_per_line=1, selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True, column_spacing=16, row_spacing=16,
            margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        scroller.set_child(self.flow)
        self.stack.add_named(scroller, "grid")

        self.status_page = Adw.StatusPage(
            icon_name="network-wireless-offline-symbolic", title="", description="")
        self.stack.add_named(self.status_page, "status")

        self.spinner_page = Adw.StatusPage(title="Looking for machines…")
        self.spinner_page.set_child(
            Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        self.stack.add_named(self.spinner_page, "loading")

    def _pill_menu_button(self):
        """Parsec-style pill that opens the options menu."""
        btn = Gtk.MenuButton()
        btn.add_css_class("pill-btn")
        btn.set_child(Gtk.Image.new_from_icon_name("avatar-default-symbolic"))
        menu = Gio.Menu()
        mouse = Gio.Menu()
        mouse.append("Desktop (cursor free)", "win.mouse-mode::desktop")
        mouse.append("Game (cursor locked)", "win.mouse-mode::game")
        menu.append_section("Mouse", mouse)
        sec1 = Gio.Menu()
        sec1.append("Show all devices", "win.show-all")
        menu.append_section(None, sec1)
        sec2 = Gio.Menu()
        sec2.append("Stream settings…", "win.settings")
        sec2.append("Refresh", "win.refresh")
        menu.append_section(None, sec2)
        sec3 = Gio.Menu()
        sec3.append("About Beam", "win.about")
        menu.append_section(None, sec3)
        btn.set_menu_model(menu)
        return btn

    def _install_actions(self):
        for name, cb in (("settings", self._open_settings),
                         ("about", self._open_about),
                         ("refresh", lambda *_: self.refresh())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        for name, cb in (("pair", self._on_pair_action),
                         ("apps", self._on_apps_action),
                         ("test", self._on_test_action)):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            a.connect("activate", cb)
            self.add_action(a)
        show_all = Gio.SimpleAction.new_stateful(
            "show-all", None,
            GLib.Variant.new_boolean(self.config.get("show_all_devices", False)))
        show_all.connect("change-state", self._on_show_all)
        self.add_action(show_all)

        mouse_mode = Gio.SimpleAction.new_stateful(
            "mouse-mode", GLib.VariantType.new("s"),
            GLib.Variant.new_string(self.config.get("mouse_mode", "desktop")))
        mouse_mode.connect("activate", self._on_mouse_mode)
        self.add_action(mouse_mode)

    # ---- provider / mode / filter --------------------------------------
    def _current_provider(self):
        return self.providers[self.provider_ids[self.provider_drop.get_selected()]]

    def _on_provider_changed(self, *_):
        self.config["provider"] = self.provider_ids[self.provider_drop.get_selected()]
        cfg.save(self.config)
        self.refresh()

    def _on_mode_toggled(self, *_):
        mode = "fullscreen" if self._fs_btn.get_active() else "windowed"
        self.config["display_mode"] = mode
        cfg.save(self.config)
        self.launcher.config = self.config

    def _on_show_all(self, action, value):
        action.set_state(value)
        self.config["show_all_devices"] = value.get_boolean()
        cfg.save(self.config)
        self._render_hosts()  # re-filter without re-probing

    def _on_mouse_mode(self, action, param):
        mode = param.get_string()
        action.set_state(param)
        self.config["mouse_mode"] = mode
        cfg.save(self.config)
        self.launcher.config = self.config
        self._toast(f"Mouse: {'cursor free' if mode == 'desktop' else 'cursor locked'}")

    # ---- refresh --------------------------------------------------------
    def refresh(self):
        provider = self._current_provider()
        if not provider.available:
            self._show_status("dialog-information-symbolic",
                              provider.label.replace(" (coming soon)", ""),
                              provider.unavailable_message)
            return
        self.stack.set_visible_child_name("loading")

        def work():
            err = provider.readiness_error()
            hosts = []
            if not err:
                hosts = provider.list_hosts()
                probe.mark_hostable(hosts)
                probe.mark_direct(provider, hosts)
            GLib.idle_add(self._on_hosts, provider, hosts, err)

        threading.Thread(target=work, daemon=True).start()

    def _on_hosts(self, provider, hosts, err):
        self._provider_err = err
        self._all_hosts = hosts
        if err:
            self._show_status("dialog-warning-symbolic",
                              "Can’t reach " + provider.label, err)
            return False
        self._render_hosts()
        return False

    def _render_hosts(self):
        show_all = self.config.get("show_all_devices", False)
        hosts = self._all_hosts if show_all else [
            h for h in self._all_hosts if h.extra.get("hostable")]
        self._hosts_by_id = {h.id: h for h in hosts}

        child = self.flow.get_first_child()
        while child:
            self.flow.remove(child)
            child = self.flow.get_first_child()

        if not hosts:
            if self._all_hosts and not show_all:
                self._show_status(
                    "network-wireless-offline-symbolic", "No hosts online",
                    "No machines are running Sunshine right now.\n"
                    "Turn on “Show all devices” to see every tailnet device.")
            else:
                self._show_status("network-wireless-offline-symbolic",
                                  "No machines",
                                  self._current_provider().empty_message)
            return
        for h in hosts:
            self.flow.append(HostCard(h, self))
        self.stack.set_visible_child_name("grid")

    def _show_status(self, icon, title, desc):
        self.status_page.set_icon_name(icon)
        self.status_page.set_title(title)
        self.status_page.set_description(desc)
        self.status_page.set_child(None)
        self.stack.set_visible_child_name("status")

    # ---- host actions ---------------------------------------------------
    def on_connect(self, host: Host):
        try:
            self.launcher.stream(self.launcher.address_for(host), display_pos=self._monitor_pos())
            disp = self.config.get("display_mode", "fullscreen")
            mouse = "cursor free" if self.config.get("mouse_mode") == "desktop" \
                else "cursor locked"
            self._toast(f"Connecting to {host.name} · {disp} · {mouse}…")
        except Exception as e:  # noqa: BLE001
            self._toast(f"Launch failed: {e}")

    def _on_pair_action(self, _action, param):
        host = self._hosts_by_id.get(param.get_string())
        if host:
            self._pair_dialog(host)

    def _on_apps_action(self, _action, param):
        host = self._hosts_by_id.get(param.get_string())
        if host:
            self._apps_dialog(host)

    def _on_test_action(self, _action, param):
        host = self._hosts_by_id.get(param.get_string())
        if host:
            self._test_dialog(host)

    def _test_dialog(self, host: Host):
        from . import diagnose

        address = self.launcher.address_for(host)
        dlg = Adw.Dialog(title=f"Test connection · {host.name}",
                         content_width=520, content_height=600)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        dlg.set_child(view)

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        view.set_content(stack)

        busy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        spinner = Adw.Spinner(width_request=48, height_request=48)
        busy.append(spinner)
        status = Gtk.Label(label="Starting…")
        status.add_css_class("dim-label")
        busy.append(status)
        note = Gtk.Label(label=f"Streams from {address} in the background\n"
                               "using your current settings. Nothing opens on screen.",
                         justify=Gtk.Justification.CENTER)
        note.add_css_class("caption")
        note.add_css_class("dim-label")
        busy.append(note)
        stack.add_named(busy, "busy")

        def show(report):
            page = Adw.PreferencesPage()
            if report.error:
                err = Adw.PreferencesGroup(title="Test failed", description=report.error)
                page.add(err)
            if report.metrics:
                group = Adw.PreferencesGroup(
                    title="Measured",
                    description=f"{address} · targets are typical for a healthy LAN stream")
                for m in report.metrics:
                    row = Adw.ActionRow(title=m.label, subtitle=m.target)
                    value = Gtk.Label(label=m.value)
                    value.add_css_class(f"diag-{m.rating}")
                    row.add_suffix(value)
                    group.add(row)
                page.add(group)
            if report.advice:
                tips = Adw.PreferencesGroup(title="What to improve")
                for tip in report.advice:
                    label = Gtk.Label(label=tip, wrap=True, xalign=0,
                                      margin_top=10, margin_bottom=10,
                                      margin_start=12, margin_end=12)
                    tips.add(label)
                page.add(tips)
            stack.add_named(page, "result")
            stack.set_visible_child_name("result")
            return False

        def work():
            report = diagnose.run(
                self.launcher, address,
                self.config.get("default_app") or "Desktop",
                progress=lambda msg: GLib.idle_add(status.set_label, msg))
            GLib.idle_add(show, report)

        threading.Thread(target=work, daemon=True).start()
        dlg.present(self)

    def _pair_dialog(self, host: Host):
        dlg = Adw.AlertDialog(
            heading=f"Pair with {host.name}",
            body=("Pick a 4-digit PIN, then enter the SAME PIN in Sunshine on "
                  f"the host (web UI at https://{host.address}:47990 → PIN)."))
        entry = Gtk.Entry(max_length=4, input_purpose=Gtk.InputPurpose.DIGITS,
                          placeholder_text="e.g. 1234", margin_top=8,
                          margin_start=12, margin_end=12)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("pair", "Pair")
        dlg.set_response_appearance("pair", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("pair")

        def on_resp(_d, resp):
            if resp != "pair":
                return
            pin = entry.get_text().strip()
            if len(pin) != 4 or not pin.isdigit():
                self._toast("PIN must be 4 digits.")
                return
            self._toast(f"Pairing… enter {pin} in Sunshine on {host.name}.")

            def work():
                ok, msg = self.launcher.pair(host.address, pin)
                GLib.idle_add(self._toast,
                              f"Paired with {host.name}." if ok
                              else f"Pairing failed: {msg or 'see Sunshine'}")
            threading.Thread(target=work, daemon=True).start()

        dlg.connect("response", on_resp)
        dlg.present(self)

    def _apps_dialog(self, host: Host):
        self._toast(f"Fetching apps on {host.name}…")

        def work():
            apps = self.launcher.list_apps(self.launcher.address_for(host))
            GLib.idle_add(self._show_apps, host, apps)
        threading.Thread(target=work, daemon=True).start()

    def _show_apps(self, host: Host, apps):
        if not apps:
            self._toast(f"No apps found (is {host.name} paired?).")
            return
        dlg = Adw.AlertDialog(heading=f"Stream from {host.name}",
                              body="Choose what to launch.")
        drop = Gtk.DropDown.new_from_strings(apps)
        default = self.config.get("default_app", "Desktop")
        if default in apps:
            drop.set_selected(apps.index(default))
        drop.set_margin_top(8)
        dlg.set_extra_child(drop)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("go", "Stream")
        dlg.set_response_appearance("go", Adw.ResponseAppearance.SUGGESTED)

        def on_resp(_d, resp):
            if resp == "go":
                app = apps[drop.get_selected()]
                self.launcher.stream(self.launcher.address_for(host), app, display_pos=self._monitor_pos())
                self._toast(f"Streaming {app} from {host.name}…")
        dlg.connect("response", on_resp)
        dlg.present(self)

    # ---- settings / about ----------------------------------------------
    def _open_settings(self, *_):
        from .settings import SettingsDialog
        SettingsDialog(self).present(self)

    def _open_about(self, *_):
        Adw.AboutDialog(
            application_name="Beam", developer_name="Simon", version="0.2",
            comments=("A Parsec-style front-end for Moonlight + Sunshine.\n"
                      "Discovery is pluggable — Tailscale now, self-hosted later."),
            license_type=Gtk.License.GPL_3_0).present(self)

    def _toast(self, text):
        self.toasts.add_toast(Adw.Toast.new(text))
        return False
