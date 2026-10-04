"""Beam main window — a Parsec-style grid of reachable machines."""
from __future__ import annotations

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib, Gio  # noqa: E402

from . import config as cfg  # noqa: E402
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

CSS = b"""
.host-card { padding: 18px; border-radius: 14px; min-width: 190px; }
.status-dot { min-width: 10px; min-height: 10px; border-radius: 10px; }
.status-dot.online  { background: #2ec27e; }
.status-dot.offline { background: #c0bfbc; }
.host-name { font-weight: 700; font-size: 1.05rem; }
.os-icon   { -gtk-icon-size: 44px; opacity: 0.85; margin-bottom: 4px; }
"""


class HostCard(Gtk.Box):
    """One machine as a Parsec-like card."""

    def __init__(self, host: Host, window: "BeamWindow"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.host = host
        self.window = window
        self.add_css_class("card")
        self.add_css_class("host-card")

        icon = Gtk.Image.new_from_icon_name(OS_ICON.get(host.os, OS_ICON[""]))
        icon.add_css_class("os-icon")
        icon.set_halign(Gtk.Align.CENTER)
        self.append(icon)

        name = Gtk.Label(label=host.name, halign=Gtk.Align.CENTER)
        name.add_css_class("host-name")
        name.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        self.append(name)

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                         halign=Gtk.Align.CENTER)
        dot = Gtk.Box()
        dot.add_css_class("status-dot")
        dot.add_css_class("online" if host.online else "offline")
        dot.set_valign(Gtk.Align.CENTER)
        status.append(dot)
        status.append(Gtk.Label(label=host.detail or host.address))
        status.get_last_child().add_css_class("dim-label")
        status.get_last_child().add_css_class("caption")
        self.append(status)

        self.append(Gtk.Box(vexpand=True))  # spacer

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                          homogeneous=False)
        connect = Gtk.Button(label="Connect", hexpand=True)
        connect.add_css_class("suggested-action")
        connect.set_sensitive(host.online)
        connect.connect("clicked", lambda *_: window.on_connect(host))
        buttons.append(connect)

        menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic")
        menu_btn.add_css_class("flat")
        menu = Gio.Menu()
        menu.append("Pair with host…", f"win.pair::{host.id}")
        menu.append("Choose app…", f"win.apps::{host.id}")
        menu_btn.set_menu_model(menu)
        buttons.append(menu_btn)
        self.append(buttons)


class BeamWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Beam")
        self.set_default_size(760, 560)
        self.config = cfg.load()
        self.launcher = MoonlightLauncher(self.config)
        self.providers = {p.id: p() for p in ALL_PROVIDERS}
        self._hosts_by_id: dict[str, Host] = {}

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
        self.toasts.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        # provider switcher
        labels = [p.label for p in self.providers.values()]
        self.provider_ids = list(self.providers.keys())
        self.provider_drop = Gtk.DropDown.new_from_strings(labels)
        start = self.config.get("provider", "tailscale")
        if start in self.provider_ids:
            self.provider_drop.set_selected(self.provider_ids.index(start))
        self.provider_drop.connect("notify::selected", self._on_provider_changed)
        header.pack_start(self.provider_drop)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic",
                             tooltip_text="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_start(refresh)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        m = Gio.Menu()
        m.append("Stream settings…", "win.settings")
        m.append("About Beam", "win.about")
        menu_btn.set_menu_model(m)
        header.pack_end(menu_btn)

        # body: scroller -> stack (grid / status)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self.stack)

        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.flow = Gtk.FlowBox(
            valign=Gtk.Align.START, max_children_per_line=4,
            min_children_per_line=1, selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True, column_spacing=14, row_spacing=14,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        scroller.set_child(self.flow)
        self.stack.add_named(scroller, "grid")

        self.status_page = Adw.StatusPage(
            icon_name="network-wireless-offline-symbolic",
            title="No machines", description="")
        self.stack.add_named(self.status_page, "status")

        self.spinner_page = Adw.StatusPage(title="Looking for machines…")
        sp = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        self.spinner_page.set_child(sp)
        self.stack.add_named(self.spinner_page, "loading")

    def _install_actions(self):
        for name, cb in (("settings", self._open_settings),
                         ("about", self._open_about)):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        for name, cb in (("pair", self._on_pair_action),
                         ("apps", self._on_apps_action)):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            a.connect("activate", cb)
            self.add_action(a)

    # ---- provider / refresh --------------------------------------------
    def _current_provider(self):
        return self.providers[self.provider_ids[self.provider_drop.get_selected()]]

    def _on_provider_changed(self, *_):
        self.config["provider"] = self.provider_ids[self.provider_drop.get_selected()]
        cfg.save(self.config)
        self.refresh()

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
            hosts = [] if err else provider.list_hosts()
            GLib.idle_add(self._on_hosts, provider, hosts, err)

        threading.Thread(target=work, daemon=True).start()

    def _on_hosts(self, provider, hosts, err):
        self._hosts_by_id = {h.id: h for h in hosts}
        child = self.flow.get_first_child()
        while child:
            self.flow.remove(child)
            child = self.flow.get_first_child()
        if err:
            self._show_status("dialog-warning-symbolic", "Can’t reach " +
                              provider.label, err)
            return
        if not hosts:
            self._show_status("network-wireless-offline-symbolic",
                              "No machines", provider.empty_message)
            return
        for h in hosts:
            self.flow.append(HostCard(h, self))
        self.stack.set_visible_child_name("grid")
        return False

    def _show_status(self, icon, title, desc):
        self.status_page.set_icon_name(icon)
        self.status_page.set_title(title)
        self.status_page.set_description(desc)
        self.status_page.set_child(None)
        self.stack.set_visible_child_name("status")

    # ---- host actions ---------------------------------------------------
    def on_connect(self, host: Host):
        try:
            self.launcher.stream(host.address)
            self._toast(f"Connecting to {host.name}…")
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

    def _pair_dialog(self, host: Host):
        dlg = Adw.AlertDialog(
            heading=f"Pair with {host.name}",
            body=("Pick a 4-digit PIN, then enter the SAME PIN in Sunshine on "
                  f"the host (its web UI at https://{host.address}:47990 → PIN)."))
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
            apps = self.launcher.list_apps(host.address)
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
                self.launcher.stream(host.address, app)
                self._toast(f"Streaming {app} from {host.name}…")
        dlg.connect("response", on_resp)
        dlg.present(self)

    # ---- settings / about ----------------------------------------------
    def _open_settings(self, *_):
        from .settings import SettingsDialog
        SettingsDialog(self).present(self)

    def _open_about(self, *_):
        about = Adw.AboutDialog(
            application_name="Beam",
            developer_name="Simon",
            version="0.1",
            comments=("A Parsec-style front-end for Moonlight + Sunshine.\n"
                      "Discovery is pluggable — Tailscale now, self-hosted "
                      "signaling later."),
            license_type=Gtk.License.GPL_3_0)
        about.present(self)

    def _toast(self, text):
        self.toasts.add_toast(Adw.Toast.new(text))
        return False
