# Beam

A Parsec-style native front-end for self-hosted game streaming. It gives you the
thing people actually miss from Parsec — *log in, your machines appear in a grid,
click to connect* — on top of the open-source **Sunshine** (host) + **Moonlight**
(stream engine) stack. No Parsec account, no ToS to break, GPL all the way down.

Native GTK4 / libadwaita. Not a web app.

## How it fits together

```
┌────────────────────┐     drives      ┌───────────────┐   streams   ┌──────────┐
│  Beam (this app)   │ ───────────────▶│   Moonlight   │────────────▶│ Sunshine │
│  UI + device list  │  moonlight CLI  │ (stream core) │   (NVENC/   │  (host)  │
└─────────┬──────────┘                 └───────────────┘   VA-API)   └──────────┘
          │ asks "which hosts?"
          ▼
   DiscoveryProvider  ◀── pluggable
     ├── TailscaleProvider   (works now — reads `tailscale status`)
     └── SelfHostedProvider  (PLACEHOLDER — your own signaling/relay, later)
```

Beam never touches the video path itself — Moonlight still does the real
streaming. Beam is the launcher + discovery brain, which is exactly the part
Moonlight leaves manual (type an IP, enter a PIN).

## Run it

```bash
python3 ~/beam/beam.py      # or launch "Beam" from your app menu
```

Requires: `python3-gi`, GTK4 + libadwaita, `tailscale`, `moonlight`. All present
on this machine.

## Using it

1. Pick a provider in the header (Tailscale is selected by default).
2. Your tailnet machines show as cards. Online ones have a green dot.
3. First time with a host: **⋯ → Pair with host…**, choose a 4-digit PIN, and
   enter the same PIN in Sunshine on that machine
   (`https://<host>:47990` → PIN).
4. **Connect** streams the default app (Desktop). **⋯ → Choose app…** picks a
   specific Sunshine app.
5. **Menu → Stream settings** sets resolution / FPS / bitrate / display mode;
   saved to `~/.config/beam/config.json`.

## The roadmap (what the placeholder is for)

Tailscale currently provides the "reachable from anywhere, no port-forwarding"
magic. To drop the Tailscale requirement, `providers/selfhosted.py` is the slot
for a self-hosted **signaling + relay** service:

- a small server (VPS or your always-on PC) holds a roster of your machines and
  brokers their connection candidates (STUN/ICE-style hole punching, TURN relay
  fallback);
- host side registers + publishes candidates, client side fetches the roster →
  that becomes `list_hosts()`, then candidates are exchanged and Moonlight is
  handed a reachable address.

It reuses the same `Host` dataclass, so when it's built the UI needs no changes —
flip `available = True` and implement `list_hosts()`.

## Layout

| File | Role |
|------|------|
| `beam/main.py` | `Adw.Application` entry point |
| `beam/window.py` | main window, card grid, pair/apps dialogs |
| `beam/settings.py` | stream-preferences dialog |
| `beam/launcher.py` | builds + runs Moonlight commands |
| `beam/config.py` | `~/.config/beam/config.json` |
| `beam/providers/base.py` | `Host` + `DiscoveryProvider` contract |
| `beam/providers/tailscale.py` | working Tailscale discovery |
| `beam/providers/selfhosted.py` | placeholder for the custom path |

## License

GPL-3.0, to stay compatible with Sunshine and Moonlight.
