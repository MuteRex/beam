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
set -euo pipefail

EDID_NAME="beam-virtual.bin"
EDID_PATH="/lib/firmware/edid/$EDID_NAME"
SELF="/usr/local/sbin/beam-virtual-display"
UNIT="/etc/systemd/system/beam-virtual-display.service"
PARAM="/sys/module/drm/parameters/edid_firmware"
# 1920x1080 @ 144/120/60 Hz, CVT-RBv2, <= 340 MHz (no HDMI 2.0 scrambling)
EDID_B64="AP///////wAIrUQBAQAAACgkAQOANR54Du6Ro1RMmSYPUFQgAAABAQEBAQEBAQEBAQEBAQEBKoKAUHA4TUAIIPgMDyghAAAeQGuAUHA4QEAIICgMDyghAAAeAAAA/QAwkB6nIgAKICAgICAgAAAA/ABCZWFtIFZpcnR1YWwKAUUCAxKBQgEQ4gBKZwMMABAAAEQUNIBQcDgfQAggGAQPKCEAAB4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARg=="

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
    echo "Installed. It will come back on at every boot."
    ;;
on) turn_on ;;
off) turn_off ;;
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
*) echo "usage: $0 install|on|off|status|uninstall" >&2; exit 2 ;;
esac
