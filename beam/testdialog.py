"""Test connection dialog."""
from __future__ import annotations

import math
import threading

from gi.repository import Adw, GLib, Gtk, Pango, PangoCairo

from . import bitrate
from . import config as cfg
from . import diagnose, probe

COLORS = {
    diagnose.GOOD: (0x9a / 255, 0xe6 / 255, 0x00 / 255),
    diagnose.OK: (0xf5 / 255, 0xc2 / 255, 0x11 / 255),
    diagnose.BAD: (0xff / 255, 0x6b / 255, 0x6b / 255),
}
TRACK = (0x26 / 255, 0x26 / 255, 0x26 / 255)
TEXT = (0xe8 / 255, 0xe8 / 255, 0xe8 / 255)
DIM = (0x80 / 255, 0x80 / 255, 0x80 / 255)

CSS = b"""
.test-hero-icon { -gtk-icon-size: 56px; color: #9ae600; }
.test-title { font-weight: 800; font-size: 1.35rem; }
.test-percent { font-weight: 800; font-size: 3rem; font-feature-settings: "tnum"; }
.test-stage { font-weight: 600; }
progressbar.beam-progress > trough { min-height: 8px; border-radius: 8px; background: #262626; }
progressbar.beam-progress > trough > progress { min-height: 8px; border-radius: 8px; background: #9ae600; }
.fact { background: #1b1b1b; border: 1px solid #262626; border-radius: 12px; padding: 10px 14px; }
.fact-value { font-weight: 700; }
.verdict { font-weight: 800; font-size: 2.1rem; }
.verdict.good { color: #9ae600; }
.verdict.ok { color: #f5c211; }
.verdict.bad { color: #ff6b6b; }
.summary-card { background: #1b1b1b; border: 1px solid #262626; border-radius: 16px; padding: 18px; }
.rec-value { font-weight: 800; font-size: 1.6rem; color: #9ae600; font-feature-settings: "tnum"; }
.stat-tile { background: #1b1b1b; border: 1px solid #262626; border-radius: 12px; padding: 10px 12px; }
.stat-value { font-weight: 700; font-size: 1.15rem; font-feature-settings: "tnum"; }
.stat-value.good { color: #9ae600; }
.stat-value.ok { color: #f5c211; }
.stat-value.bad { color: #ff6b6b; }
"""


class LadderChart(Gtk.DrawingArea):

    def __init__(self, steps: list[diagnose.Step]):
        super().__init__(content_height=150, hexpand=True)
        self.steps = steps
        self.current: int | None = None
        self._phase = 0.0
        self._tick = None
        self.set_draw_func(self._draw)

    def update(self, steps, current):
        self.steps, self.current = steps, current
        running = current is not None and current < len(steps) and not steps[current].rating
        if running and self._tick is None:
            self._tick = self.add_tick_callback(self._on_tick)
        elif not running and self._tick is not None:
            self.remove_tick_callback(self._tick)
            self._tick = None
        self.queue_draw()

    def _on_tick(self, _widget, clock):
        self._phase = (clock.get_frame_time() / 1e6) % 1.2 / 1.2
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr, width, height):
        n = len(self.steps)
        if not n:
            return
        top_pad, label_h = 20, 22
        gap = 12
        bar_w = min(64, (width - gap * (n - 1)) / n)
        total_w = bar_w * n + gap * (n - 1)
        x0 = (width - total_w) / 2
        usable = height - top_pad - label_h
        lo = math.log(min(s.kbps for s in self.steps))
        hi = math.log(max(s.kbps for s in self.steps))

        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string("Sans Bold 9")
        layout.set_font_description(font)

        for i, step in enumerate(self.steps):
            x = x0 + i * (bar_w + gap)
            frac = 0.35 + 0.65 * ((math.log(step.kbps) - lo) / (hi - lo) if hi > lo else 1)
            h = usable * frac
            y = top_pad + usable - h

            _rounded(cr, x, y, bar_w, h, 7)
            cr.set_source_rgb(*TRACK)
            cr.fill()

            if step.rating:
                cr.set_source_rgb(*COLORS[step.rating])
                _rounded(cr, x, y, bar_w, h, 7)
                cr.fill()
            elif i == self.current:
                alpha = 0.35 + 0.45 * (0.5 - 0.5 * math.cos(self._phase * 2 * math.pi))
                cr.set_source_rgba(*COLORS[diagnose.GOOD], alpha)
                _rounded(cr, x, y, bar_w, h, 7)
                cr.fill()

            mark = ""
            if step.rating == diagnose.BAD and step.drop_pct is None:
                mark = "✕"
            elif step.drop_pct is not None:
                mark = f"{step.drop_pct:.1f}%"
            if mark:
                layout.set_text(mark, -1)
                tw, th = layout.get_pixel_size()
                cr.set_source_rgb(*(COLORS[step.rating] if step.rating else DIM))
                cr.move_to(x + (bar_w - tw) / 2, y - th - 2)
                PangoCairo.show_layout(cr, layout)

            layout.set_text(f"{step.kbps // 1000}", -1)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgb(*(TEXT if step.rating or i == self.current else DIM))
            cr.move_to(x + (bar_w - tw) / 2, height - label_h + 4)
            PangoCairo.show_layout(cr, layout)


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _label(text, *classes, **kw):
    label = Gtk.Label(label=text, **kw)
    for c in classes:
        label.add_css_class(c)
    return label


def _fact(icon: str, value: str, caption: str) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, hexpand=True)
    box.add_css_class("fact")
    box.append(Gtk.Image(icon_name=icon))
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    text.append(_label(value, "fact-value", xalign=0))
    text.append(_label(caption, "caption", "dim-label", xalign=0))
    box.append(text)
    return box


def _tile(value: str, caption: str, rating: str) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    box.add_css_class("stat-tile")
    box.append(_label(value, "stat-value", rating, xalign=0))
    box.append(_label(caption, "caption", "dim-label", xalign=0))
    return box


class TestDialog(Adw.Dialog):
    def __init__(self, window, host, host_key: str):
        super().__init__(title=f"Test connection · {host.name}",
                         content_width=540, content_height=640)
        self.window, self.host, self.host_key = window, host, host_key
        self.config = window.config
        self.launcher = window.launcher
        self.address = self.launcher.address_for(host)
        self.route = bitrate.route_of(probe.is_lan_address(self.address))
        self.step_seconds = int(self.config.get("test_step_seconds") or 5)
        self.stop = threading.Event()
        self.connect("closed", lambda *_: self.stop.set())

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display() if self.get_display() else window.get_display(),
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        view.set_content(self.stack)
        self._build_intro()

    # ---- intro ----------------------------------------------------------
    def route_text(self) -> str:
        return ("your home network" if self.route == bitrate.HOME
                else "the internet (Tailscale)")

    def _build_intro(self):
        seconds, mb = diagnose.estimate(self.route, self.step_seconds)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                       margin_top=24, margin_bottom=24, margin_start=28, margin_end=28,
                       valign=Gtk.Align.CENTER)
        page.append(Gtk.Image(icon_name="network-transmit-receive-symbolic",
                              css_classes=["test-hero-icon"]))
        page.append(_label(f"How well does {self.host.name} stream to you?", "test-title",
                           wrap=True, justify=Gtk.Justification.CENTER))
        page.append(_label(
            f"Beam streams from {self.host.name} in the background over {self.route_text()}, "
            "raising the bitrate step by step until frames start to drop. Then it "
            "recommends a bitrate with room to spare. Nothing opens on screen.",
            "dim-label", wrap=True, justify=Gtk.Justification.CENTER))

        facts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True,
                        margin_top=6)
        facts.append(_fact("network-wired-symbolic" if self.route == bitrate.HOME
                           else "network-cellular-signal-good-symbolic",
                           "Home network" if self.route == bitrate.HOME else "Over the internet",
                           self.address))
        facts.append(_fact("alarm-symbolic", f"About {seconds} s", "up to 5 steps"))
        facts.append(_fact("folder-download-symbolic", f"Up to {mb:.0f} MB",
                           "of data" if self.route == bitrate.HOME else "of mobile data, if on a hotspot"))
        page.append(facts)

        start = Gtk.Button(label="Start test", halign=Gtk.Align.CENTER, margin_top=8)
        start.add_css_class("suggested-action")
        start.add_css_class("pill")
        start.connect("clicked", lambda *_: self._confirm_metered())
        page.append(start)
        self.stack.add_named(page, "intro")

    def _confirm_metered(self):
        """On a metered connection (a phone hotspot) ask first: the test can
        use tens of MB."""
        if not probe.network_metered():
            self._start()
            return
        _seconds, mb = diagnose.estimate(self.route, self.step_seconds)
        dlg = Adw.AlertDialog(
            heading="Use mobile data?",
            body=(f"This connection is metered. The test can use up to {mb:.0f} MB "
                  "of data."))
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("start", "Start test")
        dlg.set_response_appearance("start", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, resp: resp == "start" and self._start())
        dlg.present(self)

    # ---- running --------------------------------------------------------
    def _build_running(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=24, margin_bottom=24, margin_start=28, margin_end=28,
                       valign=Gtk.Align.CENTER)
        self.percent = _label("0%", "test-percent")
        page.append(self.percent)
        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("beam-progress")
        page.append(self.bar)
        self.stage = _label("Starting…", "test-stage")
        page.append(self.stage)

        self.chart = LadderChart([diagnose.Step(k) for k in diagnose.ladder_for(self.route)])
        self.chart.set_margin_top(12)
        page.append(self.chart)
        page.append(_label("Mbps per step · % = frames lost", "caption", "dim-label"))

        stop = Gtk.Button(label="Stop", halign=Gtk.Align.CENTER, margin_top=6)
        stop.add_css_class("pill")
        stop.connect("clicked", self._on_stop)
        page.append(stop)
        self.stop_button = stop
        self.stack.add_named(page, "running")

    def _on_stop(self, button):
        self.stop.set()
        button.set_sensitive(False)
        button.set_label("Stopping after this step…")

    def _start(self):
        if self.stack.get_child_by_name("running") is None:
            self._build_running()
        self.stop.clear()
        self.stop_button.set_sensitive(True)
        self.stop_button.set_label("Stop")
        self.stack.set_visible_child_name("running")
        app = self.config.get("default_app") or "Desktop"

        def work():
            report = diagnose.run(self.launcher, self.address, app,
                                  step_seconds=self.step_seconds,
                                  progress=lambda p: GLib.idle_add(self._on_progress, p),
                                  stop=self.stop)
            GLib.idle_add(self._show_result, report)

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, p: diagnose.Progress):
        self.percent.set_label(f"{int(p.fraction * 100)}%")
        self.bar.set_fraction(p.fraction)
        self.stage.set_label(p.stage)
        self.chart.update(p.steps, p.current)
        return False

    # ---- result ---------------------------------------------------------
    def _show_result(self, report: diagnose.Report):
        old = self.stack.get_child_by_name("result")
        if old is not None:
            self.stack.remove(old)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                       margin_top=18, margin_bottom=24, margin_start=22, margin_end=22)
        scroll.set_child(page)

        page.append(self._summary_card(report))

        if report.ping_ms is not None:
            tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
            home = self.route == bitrate.HOME
            tiles.append(_tile(f"{report.ping_ms:.0f} ms" if report.ping_ms >= 10 else f"{report.ping_ms:.1f} ms",
                               "Latency", diagnose._rate(report.ping_ms, 5, 15) if home
                               else diagnose._rate(report.ping_ms, 30, 80)))
            tiles.append(_tile(f"±{report.jitter_ms:.1f} ms", "Jitter",
                               diagnose._rate(report.jitter_ms or 0, 2 if home else 8, 6 if home else 25)))
            tiles.append(_tile(f"{report.loss_pct:.0f}%", "Packet loss",
                               diagnose.GOOD if not report.loss_pct else
                               diagnose.OK if report.loss_pct <= 2 else diagnose.BAD))
            page.append(tiles)

        if any(s.rating for s in report.steps):
            chart_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            chart_card.add_css_class("stat-tile")
            chart_card.append(_label("Bitrate steps", "heading", xalign=0))
            chart = LadderChart(report.steps)
            chart.update(report.steps, None)
            chart_card.append(chart)
            chart_card.append(_label("Mbps per step · % = frames lost", "caption", "dim-label"))
            page.append(chart_card)

        if report.advice:
            tips = Adw.PreferencesGroup(title="Tips")
            for tip in report.advice:
                tips.add(_label(tip, wrap=True, xalign=0, margin_top=10, margin_bottom=10,
                                margin_start=12, margin_end=12))
            page.append(tips)

        if report.metrics:
            details = Adw.PreferencesGroup(title="Details")
            expander = Adw.ExpanderRow(title="Measured timings",
                                       subtitle=f"{report.address} · from the best clean step")
            expander.set_use_markup(False)
            for m in report.metrics:
                row = Adw.ActionRow(title=m.label, subtitle=m.target, use_markup=False)
                row.add_suffix(_label(m.value, f"diag-{m.rating}"))
                expander.add_row(row)
            details.add(expander)
            page.append(details)

        again = Gtk.Button(label="Run again", halign=Gtk.Align.CENTER)
        again.add_css_class("pill")
        again.connect("clicked", lambda *_: self._start())
        page.append(again)

        self.stack.add_named(scroll, "result")
        self.stack.set_visible_child_name("result")
        return False

    def _summary_card(self, report: diagnose.Report) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("summary-card")
        rating = report.verdict_rating or diagnose.BAD
        word = report.verdict or ("Test failed" if report.error else "Poor")
        card.append(_label(word, "verdict", rating, xalign=0))
        card.append(_label(f"{self.host.name} over {self.route_text()}", "dim-label", xalign=0))

        if report.error and report.recommended_kbps is None:
            card.append(_label(report.error, wrap=True, xalign=0, margin_top=6))
            return card

        rec = report.recommended_kbps
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=10)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(_label("Recommended bitrate", "caption", "dim-label", xalign=0))
        text.append(_label(bitrate.label(rec), "rec-value", xalign=0))
        hint = bitrate.usage_hint(rec)
        text.append(_label(hint[:1].upper() + hint[1:], "caption", "dim-label", xalign=0))
        row.append(text)

        current = bitrate.host_limit(self.config, self.host_key, self.route)
        use = Gtk.Button(valign=Gtk.Align.CENTER)
        use.add_css_class("pill")
        if current == rec:
            use.set_label("In use")
            use.set_sensitive(False)
        else:
            use.set_label(f"Use for {self.host.name}")
            use.add_css_class("suggested-action")
            use.connect("clicked", self._use, rec)
        row.append(use)
        card.append(row)

        where = "at home" if self.route == bitrate.HOME else "away from home"
        card.append(_label(f"Saved per computer, for streams {where}. Change or remove it in Settings.",
                           "caption", "dim-label", xalign=0, wrap=True, margin_top=4))
        return card

    def _use(self, button, kbps: int):
        saved = dict(self.config.get("host_bitrates") or {})
        entry = dict(saved.get(self.host_key) or {})
        entry["name"] = self.host.name
        entry[self.route] = kbps
        saved[self.host_key] = entry
        self.config["host_bitrates"] = saved
        cfg.save(self.config)
        button.set_label("In use")
        button.remove_css_class("suggested-action")
        button.set_sensitive(False)
