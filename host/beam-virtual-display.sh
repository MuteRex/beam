#!/bin/bash
# Beam virtual display: a real 1080p display at up to 144 Hz on an unused HDMI
# port, with nothing plugged in, so Sunshine can stream more than the 60 Hz the
# laptop's own panel can show.
#
# It loads a custom EDID (made by make_edid.py, embedded below) for the port and
# forces the port "connected"; the GPU then drives it like a monitor. No reboot,
# works with Secure Boot. "install" also adds a boot service so it comes back.
#
#   sudo bash beam-virtual-display.sh install    # set up + turn on + start at boot
#   sudo bash beam-virtual-display.sh on|off     # toggle now
#   bash beam-virtual-display.sh status
#   sudo bash beam-virtual-display.sh uninstall
#
# Sunshine runs these around each stream (added to sunshine.conf by install):
#   beam-virtual-display stream-start   # virtual display becomes the only screen
#   beam-virtual-display stream-stop    # back to the built-in screen only
# Both accept --dry-run to print the layout without applying it.
set -euo pipefail

EDID_NAME="beam-virtual.bin"
EDID_PATH="/lib/firmware/edid/$EDID_NAME"
SELF="/usr/local/sbin/beam-virtual-display"
UNIT="/etc/systemd/system/beam-virtual-display.service"
PARAM="/sys/module/drm/parameters/edid_firmware"
# 1920x1080 @ 144/120/60 Hz, CVT-RBv2, <= 340 MHz (no HDMI 2.0 scrambling)
EDID_B64="AP///////wAIrUQBAQAAACgkAQOANR54Du6Ro1RMmSYPUFQgAAABAQEBAQEBAQEBAQEBAQEBKoKAUHA4TUAIIPgMDyghAAAeQGuAUHA4QEAIICgMDyghAAAeAAAA/QAwkB6nIgAKICAgICAgAAAA/ABCZWFtIFZpcnR1YWwKAUUCAxKBQgEQ4gBKZwMMABAAAEQUNIBQcDgfQAggGAQPKCEAAB4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARg=="

SUNSHINE_PREP='global_prep_cmd = [{"do":"/usr/local/sbin/beam-virtual-display stream-start","undo":"/usr/local/sbin/beam-virtual-display stream-stop"}]'

# Switches GNOME's monitor layout through Mutter's DisplayConfig D-Bus API.
#   virtual: only the Beam virtual display, highest refresh (temporary layout)
#   builtin: only the built-in panel (saved, so it's the normal layout)
set_layout() {
    python3 - "$@" <<'PY'
import json
import os
import sys
import gi
from gi.repository import Gio, GLib

target, dry_run = sys.argv[1], "--dry-run" in sys.argv
# Layout from before the stream, restored afterwards. Only in the user's private
# runtime dir: a fixed name in shared /tmp could be pre-planted as a symlink.
runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
st = os.stat(runtime) if os.path.isdir(runtime) else None
if st is None or st.st_uid != os.getuid() or st.st_mode & 0o077:
    sys.exit(f"beam-virtual-display: no private runtime dir ({runtime}); not changing the layout")
state = os.path.join(runtime, "beam-virtual-display.layout")
bus = Gio.bus_get_sync(Gio.BusType.SESSION)

def call(method, args=None):
    return bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                         "org.gnome.Mutter.DisplayConfig", method, args, None,
                         Gio.DBusCallFlags.NONE, 5000, None).unpack()

serial, monitors, logical, _props = call("GetCurrentState")

def apply(layout, method, what):
    print(f"{'would apply' if dry_run else 'applying'} ({'temporary' if method == 1 else 'saved'}): {what}")
    if not dry_run:
        call("ApplyMonitorsConfig", GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, method, layout, {})))

current_mode = {}
for (conn, *_rest), modes, _props in monitors:
    for m in modes:
        if m[6].get("is-current"):
            current_mode[conn] = m[0]

if target == "builtin" and os.path.exists(state):
    # Put back exactly what was there before the stream
    with open(state) as f:
        saved = json.load(f)
    available = {conn for (conn, *_r), _m, _p in monitors}
    layout = [(x, y, sc, t, prim, [(c, mode, {}) for c, mode in mons if c in available])
              for x, y, sc, t, prim, mons in saved]
    layout = [lm for lm in layout if lm[5]]
    if layout:
        apply(layout, 2, ", ".join(f"{m[0]} {m[1]}" for lm in layout for m in lm[5]))
        if not dry_run:
            os.remove(state)
        sys.exit(0)
virtual = builtin = other = None
for (conn, _vendor, product, _serial), modes, props in monitors:
    entry = (conn, modes)
    if product == "Beam Virtual":
        virtual = entry
    elif props.get("is-builtin"):
        builtin = entry
    elif other is None:
        other = entry

chosen = virtual if target == "virtual" else (builtin or other)
if chosen is None:
    print(f"beam-virtual-display: no {target} display found; leaving layout unchanged")
    sys.exit(0)

conn, modes = chosen
if target == "virtual":
    # Highest refresh at the largest size
    mode = max(modes, key=lambda m: (m[1] * m[2], m[3]))
else:
    mode = next((m for m in modes if m[6].get("is-preferred")), modes[0])

# Keep the panel's current scale if it's showing, otherwise its default
scale = mode[4]
for _x, _y, lscale, _t, _primary, lmons, _p in logical:
    if any(m[0] == conn for m in lmons):
        scale = lscale

if target == "virtual" and not dry_run:
    # Remember the current layout so stream-stop can restore it
    with open(state, "w") as f:
        json.dump([(x, y, sc, t, prim, [(m[0], current_mode.get(m[0], "")) for m in mons])
                   for x, y, sc, t, prim, mons, _p in logical], f)

layout = [(0, 0, scale, 0, True, [(conn, mode[0], {})])]
# Temporary while streaming; saved when falling back to the panel
apply(layout, 1 if target == "virtual" else 2, f"{conn} {mode[0]} scale {scale}")
PY
}

need_root() { [ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }; }

# First HDMI connector with nothing plugged in (or the one we already forced)
connector() {
    for c in /sys/class/drm/card*-HDMI-A-*; do
        [ -e "$c/status" ] || continue
        if [ "$(cat "$c/status")" = disconnected ] || grep -q "${c##*/card?-}" "$PARAM" 2>/dev/null; then
            echo "$c"; return
        fi
    done
    for c in /sys/class/drm/card*-HDMI-A-*; do [ -e "$c/status" ] && { echo "$c"; return; }; done
    echo "No HDMI connector found." >&2; exit 1
}

turn_on() {
    need_root
    [ -f "$EDID_PATH" ] || { echo "EDID missing; run install first." >&2; exit 1; }
    local c name
    c="$(connector)"; name="${c##*/card?-}"
    echo "$name:edid/$EDID_NAME" > "$PARAM"
    echo on > "$c/status"
    # Give the driver a moment to read the EDID and list modes
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        grep -q 1920x1080 "$c/modes" 2>/dev/null && break
        sleep 0.3
    done
    echo "Virtual display on $name: $(cat "$c/status"), modes: $(sort -u "$c/modes" | tr '\n' ' ')"
}

turn_off() {
    need_root
    local c; c="$(connector)"
    echo detect > "$c/status"
    echo -n "" > "$PARAM" || true
    echo "Virtual display off (${c##*/card?-}: $(cat "$c/status"))."
}

case "${1:-status}" in
install)
    need_root
    # Installs a copy of this file, so it must be run from one (not piped to bash)
    if [ ! -f "$0" ] || ! grep -q "^# Beam virtual display:" "$0"; then
        echo "Run install from the downloaded file: sudo bash beam-virtual-display.sh install" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$EDID_PATH")"
    echo "$EDID_B64" | base64 -d > "$EDID_PATH"
    install -m 0755 "$0" "$SELF"
    cat > "$UNIT" <<UNITEOF
[Unit]
Description=Beam virtual high-refresh display for Sunshine
After=systemd-modules-load.service
Before=display-manager.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$SELF on
ExecStop=$SELF off

[Install]
WantedBy=graphical.target
UNITEOF
    systemctl daemon-reload
    systemctl enable beam-virtual-display.service
    turn_on
    if [ -n "${SUDO_USER:-}" ]; then
        user_home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
        conf="$user_home/.config/sunshine/sunshine.conf"
        sudo -u "$SUDO_USER" mkdir -p "$(dirname "$conf")"
        sudo -u "$SUDO_USER" touch "$conf"
        if ! grep -q "beam-virtual-display stream-start" "$conf"; then
            if grep -q "^global_prep_cmd" "$conf"; then
                echo "Note: $conf already has global_prep_cmd; add Beam's hooks by hand:" >&2
                echo "  $SUNSHINE_PREP" >&2
            else
                echo "$SUNSHINE_PREP" | sudo -u "$SUDO_USER" tee -a "$conf" >/dev/null
                echo "Sunshine will switch to the virtual display while streaming."
            fi
        fi
        uid="$(id -u "$SUDO_USER")"
        # The panel stays the normal screen; the virtual one is only used while streaming
        sudo -u "$SUDO_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
            "$SELF" stream-stop || true
        echo "Restart Sunshine to load the hooks (this ends any current stream):"
        echo "  systemctl --user restart app-dev.lizardbyte.app.Sunshine.service"
    fi
    echo "Installed. It will come back on at every boot."
    ;;
on) turn_on ;;
off) turn_off ;;
stream-start)
    set_layout virtual "${2:-}"
    # Let Mutter finish the modeset before Sunshine starts capturing
    [ "${2:-}" = --dry-run ] || sleep 1.5
    ;;
stream-stop) set_layout builtin "${2:-}" ;;
uninstall)
    need_root
    systemctl disable --now beam-virtual-display.service 2>/dev/null || true
    turn_off || true
    rm -f "$UNIT" "$SELF" "$EDID_PATH"
    systemctl daemon-reload
    echo "Removed."
    ;;
status)
    c="$(connector)"
    echo "${c##*/card?-}: $(cat "$c/status") ($(cat "$c/enabled")), firmware: '$(cat "$PARAM")'"
    echo "modes: $(sort -u "$c/modes" 2>/dev/null | tr '\n' ' ')"
    ;;
*) echo "usage: $0 install|on|off|status|stream-start|stream-stop|uninstall" >&2; exit 2 ;;
esac
