# Beam

A Parsec-style native front-end for self-hosted game streaming: your machines
appear in a grid, click to connect. Built on the open-source **Sunshine** (host)
+ **Moonlight** (stream engine) stack. No account, GPL all the way down.

Native GTK4 / libadwaita (Python + PyGObject). Not a web app.

## How it fits together

```
┌────────────────────┐     drives      ┌─────────────────────┐   streams   ┌──────────┐
│  Beam (this app)   │ ──────────────▶ │  Moonlight (fork:   │ ──────────▶ │ Sunshine │
│  UI + device list  │  moonlight CLI  │  in-stream Beam     │             │  (host)  │
└─────────┬──────────┘                 │  menu + stats)      │             └──────────┘
          │ "which hosts?"             └─────────────────────┘
          ▼
   DiscoveryProvider  ◀── pluggable
     ├── Automatic      merges Local + Tailscale per machine, LAN route first
     ├── Local network  Avahi mDNS (_nvstream._tcp) over D-Bus
     ├── Tailscale      `tailscale status --json`
     └── Self-hosted    placeholder for a signaling + relay server
```

Beam never touches the video path; Moonlight does the streaming. Beam is the
launcher and discovery layer: the part Moonlight leaves manual.

## Features

- Card grid of hosts that are actually running Sunshine (port probe), with route
  chips (LAN / Tailscale / Tailscale relay); the fastest route is used.
- One-click Connect, Fullscreen/Windowed, Desktop (cursor free) / Game (cursor
  locked) mouse modes, pairing and app picker dialogs.
- Settings for every Moonlight stream option, always passed explicitly so
  Moonlight's own saved preferences never change a Beam stream.
- **Test connection…**: ping, host encoder check and a short headless stream
  measured with your settings, with advice.
- With the Moonlight fork: a clickable in-stream **Beam pill** and menu (mouse
  mode, fullscreen, stats level, paste, release mouse, minimize, disconnect),
  a three-level performance stats panel, and clipboard paste typed as real
  keystrokes (press Paste again to stop a long paste).

## Run it

```bash
python3 beam.py
```

Needs `python3-gi`, GTK 4 + libadwaita ≥ 1.6, and Moonlight. Optional:
`tailscale` (Tailscale provider), `avahi-daemon` (local discovery), `weston`
(Test connection / benchmark).

1. First time with a host: **⋯ → Pair with host…**, pick a 4-digit PIN, enter
   the same PIN in Sunshine's web UI on that machine (`https://<host>:47990`).
2. **Connect** streams the default app (Desktop); **⋯ → Choose app…** picks one.
3. Settings (Ctrl+,) are saved to `~/.config/beam/config.json`.

Beam watches each stream and says how it ended ("isn't paired", "couldn't
reach", "connection dropped"). Moonlight's output for each stream is kept in
`~/.local/state/beam/logs/` (last 20). Ending a **Desktop** stream also ends the
host's Desktop session, so a host's own screen comes back after streaming a
virtual display; games are never quit automatically.

Beam also learns each host's real frame rate from the end-of-stream stats. If
you ask for more than a host delivered last time (usually its screen's refresh
rate), Settings says so under Frame rate, and Connect asks first: Continue,
Don't show again for this host, or Cancel. Settings → "Show refresh-rate
warnings again" brings muted warnings back.

## The Moonlight fork

Beam prefers a self-built fork at `~/beam-moonlight/app/moonlight` (branch
`beam-overlay` of moonlight-qt), else the system or snap Moonlight. Set a
different path in Settings → Advanced.

```bash
git clone --recursive -b beam-overlay <your fork URL> ~/beam-moonlight
cd ~/beam-moonlight && qmake6 && make -j"$(nproc)" release
```

Build dependencies (Ubuntu): `build-essential nasm qt6-base-dev
qt6-declarative-dev libqt6svg6-dev qt6-wayland libsdl2-dev libsdl2-ttf-dev
libopus-dev libssl-dev libavcodec-dev libavformat-dev libswscale-dev libva-dev
libvdpau-dev libdrm-dev libegl1-mesa-dev libgl1-mesa-dev libxkbcommon-dev
wayland-protocols` plus the `qml6-module-qtquick*` modules.

The fork reads these environment variables, which Beam sets:
`BEAM_HIDE_PILL=1`, `BEAM_STATS_LEVEL=basic|standard|advanced`,
`BEAM_DISPLAY_POS=x,y` (monitor to open on; Wayland can't tell Qt).

## Host: virtual high-refresh display

A host whose panel is 60 Hz only gives Sunshine 60 new frames a second.
`host/beam-virtual-display.sh` forces an unused HDMI port connected with a
custom 1080p 144/120/60 Hz EDID (`host/make_edid.py`), and hooks Sunshine so
streams use it. By default the built-in screen **mirrors** the virtual display
while streaming, so it never goes dark; `set-mode virtual` makes the virtual
display the only screen instead (if GNOME won't mirror, the layout is left as
it is rather than blanking the panel). Works with Secure Boot, no
reboot (Linux, GNOME/Mutter, Intel i915 tested).

To copy it to the host, `bash host/serve.sh` serves it over your Tailscale IP
and prints a command that checks its SHA-256 before running it as root.

Sunshine only runs a hook's undo step when the streamed app quits, not when a
client disconnects, so Beam ends Desktop sessions on disconnect. As a backstop,
`install` also adds a watchdog to the desktop session that restores the built-in
screen if the virtual display is still on ~40 s after Sunshine stopped streaming
(e.g. Sunshine crashed). A session left paused by another client (not Beam)
still needs quitting from that client.

```bash
sudo bash beam-virtual-display.sh install   # EDID + boot service + Sunshine hooks
bash beam-virtual-display.sh status
bash beam-virtual-display.sh report          # screens, modes, what Sunshine captures
bash beam-virtual-display.sh set-mode mirror # or: virtual
sudo bash beam-virtual-display.sh uninstall
```

## Benchmark

```bash
python3 -m beam.bench <host> [--seconds 30] [--only codec,fps]
```

Streams inside an invisible headless Weston (real EGL + VAAPI path) and prints
host / network / decode / render latency per configuration.

## Security notes

- Everything discovered on the network is untrusted. Addresses from mDNS,
  Tailscale and serverinfo are validated before reaching any command line,
  host-supplied values are passed after `--`, serverinfo reads are capped and
  never follow redirects, and host names are shown as plain text, never markup.
- A Sunshine host's `uniqueid` is self-reported; Beam only uses it to group
  routes. Moonlight's pinned host certificate (set at pairing) is what proves
  which machine you connect to. **Only pair with machines you control**: a
  paired host receives your keyboard, mouse and anything you paste.
- `moonlight pair --pin` puts the one-time PIN on the command line, so other
  local users can briefly see it in `ps`.

## Layout

| Path | Role |
|------|------|
| `beam/main.py` | `Adw.Application` entry point |
| `beam/window.py` | main window, card grid, pair / apps / test dialogs |
| `beam/settings.py` | settings dialog (General + Advanced) |
| `beam/options.py` | every Moonlight option, shared by UI and command line |
| `beam/launcher.py` | builds and runs Moonlight commands |
| `beam/config.py` | `~/.config/beam/config.json` (type-checked, atomic writes) |
| `beam/probe.py` | address validation, Sunshine port probe, serverinfo |
| `beam/diagnose.py`, `beam/bench.py` | Test connection and the benchmark |
| `beam/providers/` | discovery providers and the `Host` contract |
| `host/` | virtual display script, EDID generator, delivery helper |
| `tests/` | `python3 -m unittest discover -s tests` |

## License

GPL-3.0, to stay compatible with Sunshine and Moonlight.
