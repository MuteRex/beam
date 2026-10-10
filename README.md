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
  Moonlight's own saved preferences never change a Beam stream. **Presets**
  (Latency / Balanced / Quality) set codec, home bitrate, V-Sync and frame
  pacing in one click.
- Separate **home** and **away** bitrates: streams off the LAN are capped at the
  Away bitrate. On a **metered** connection (NetworkManager's flag, e.g. a phone
  hotspot) every stream is capped at it, and cards show the data an hour of
  streaming would use.
- **Test connection…** (⋯ menu): ping and host encoder check, then headless
  streams at rising bitrates (10–80 Mbps at home, 3–25 Mbps away) until frames
  drop, with live progress. It recommends a bitrate with headroom, which you
  can save for that computer and route. Asks first on a metered connection.
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
host's Desktop session (there is nothing to resume); games are never quit
automatically.

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
| `tests/` | `python3 -m unittest discover -s tests` |

## License

GPL-3.0, to stay compatible with Sunshine and Moonlight.
