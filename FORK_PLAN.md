# Beam — Moonlight fork plan (in-session clickable overlay pill)

Goal: fork Moonlight (`moonlight-qt`) and add a Parsec-style **clickable
in-session pill** that opens an options menu *drawn over the stream* (including
over fullscreen games). This requires modifying Moonlight itself because it owns
the fullscreen render surface — nothing external can reliably draw over it.

Picking the fork gives full control over the whole in-session experience, which
is why we chose it over the hotkey-only path.

---

## Status at end of previous session (2026-10-04)

- **Beam launcher app** (the front-end) is built and working: `~/beam/`
  (v0.3). Parsec-style UI, Tailscale discovery, host filtering, Desktop/Game
  mouse mode. It currently drives the **snap** Moonlight.
- **Moonlight source already cloned** with submodules at `~/beam-moonlight/`
  (17 MB, `--recursive`, depth 1). Build system is **qmake** (`moonlight-qt.pro`).
- **Build NOT yet done.** No Qt6/SDL2 dev toolchain installed yet (confirmed: 0
  Qt6/SDL2 -dev packages present; `git`, `g++` present; no `cmake`/`qmake6`/`ninja`).
- Disk: root partition `/` at **95% (22 GB free)**. The toolchain is ~150
  packages (~couple GB). It fits but it's tight — consider freeing space first.

### Key source findings (so we don't re-investigate)
- Overlay rendering already exists: `app/streaming/video/overlaymanager.{h,cpp}`
  — `OverlayManager` + `IOverlayRenderer`. Overlays are **text surfaces**
  (SDL_ttf), currently types `OverlayDebug` (perf stats) and
  `OverlayStatusUpdate` (connection warnings). Passive, no input.
- In-session shortcut/combo table: `app/streaming/input/input.cpp` lines ~83+
  (`m_SpecialKeyCombos[...]`), handlers in `app/streaming/input/keyboard.cpp`.
  Existing combos (Ctrl+Alt+Shift+KEY): Q=quit, Z=ungrab mouse, X=toggle
  fullscreen, S=toggle stats, M=toggle mouse mode, C=toggle cursor hide,
  D=minimize, V=paste. **These handler functions are what the pill menu will
  call** — the actions already exist; we're adding a clickable entry point.
- Mouse input: `app/streaming/input/mouse.cpp`.
- Renderers that actually blit overlays live under
  `app/streaming/video/ffmpeg-renderers/` (EGL/Vulkan/VAAPI/etc.).

---

## Phase 0 — Prep (low risk)

1. (Optional but recommended) free disk on `/` — see
   `[[system-profile-simon-gaming-pc]]` cleanup notes. Aim for >25 GB free.
2. Submodules already pulled; if stale: `cd ~/beam-moonlight && git submodule
   update --init --recursive`.

## Phase 1 — Toolchain install (the heavy, system-wide step)

Use **pkexec** (sudo can't prompt in this env — see memory). One install:

```bash
pkexec apt update
pkexec apt install -y \
  build-essential nasm \
  libegl1-mesa-dev libgl1-mesa-dev libopus-dev libsdl2-dev libsdl2-ttf-dev \
  libssl-dev libavcodec-dev libavformat-dev libswscale-dev libva-dev \
  libvdpau-dev libxkbcommon-dev wayland-protocols libdrm-dev \
  qt6-base-dev qt6-declarative-dev libqt6svg6-dev qt6-wayland \
  qml6-module-qtquick-controls qml6-module-qtquick-templates \
  qml6-module-qtquick-layouts qml6-module-qtqml-workerscript \
  qml6-module-qtquick-window qml6-module-qtquick
```

(Optional Vulkan renderer: also `libplacebo-dev` ≥ v7.349.0 + FFmpeg ≥ 6.1.
Skip for first build.)

## Phase 2 — Baseline build (prove it compiles unmodified)

```bash
cd ~/beam-moonlight
qmake6            # if missing, the pkg is qt6-base-dev; binary may be 'qmake6'
make -j"$(nproc)" release
# Output binary: app/moonlight  (run it directly to smoke-test a stream)
```

Verify the self-built binary streams to the vivobook before changing anything.
If it works, commit a branch: `git switch -c beam-overlay`.

## Phase 3 — The clickable overlay pill (the actual feature)

Design (reuses existing overlay + combo machinery):

1. **New overlay type** in `overlaymanager.h`: add `OverlayControls` to the
   enum (before `OverlayMax`). Render it as a small pill surface — start with a
   text glyph like `☰` or `⚙` (SDL_ttf already in use); upgrade to a drawn
   rounded rect later.
2. **Known screen rect for hit-testing.** Overlays are positioned by each
   renderer. Simplest path: anchor the pill at a fixed corner (e.g. top-center)
   and have `OverlayManager` store the last-drawn rect (expose a getter), or
   compute the same anchor math in the input handler. Store rect in window
   coords.
3. **Click handling** in `mouse.cpp` / input dispatch: when a left-click lands
   inside the pill rect, toggle an **expanded menu** (a second overlay listing:
   Disconnect / Toggle fullscreen / Mouse mode / Stats / Minimize). Clicks on
   menu items call the **existing** `KeyCombo*` handler functions directly
   (don't duplicate logic).
4. **State machine**: collapsed pill ↔ expanded menu; auto-collapse on action
   or outside-click.
5. **Mouse-capture nuance**: in Game mode the OS cursor is hidden/relative, so
   the pill is clickable mainly in Desktop/absolute mode or after Ctrl+Alt+
   Shift+Z. Decide whether the pill also appears in game mode (e.g. only when
   input is ungrabbed). Document the final behavior.

Keep the diff small and in its own files/sections so rebasing on upstream stays
easy.

## Phase 4 — Wire Beam to the forked binary

- Add a config key in `~/beam/beam/config.py`: `"moonlight_bin": ""` (empty =
  auto). In `~/beam/beam/launcher.py` `_moonlight_bin()`, prefer
  `config["moonlight_bin"]` when set, else `~/beam-moonlight/app/moonlight`,
  else snap. Add a Settings row to point at the built binary.
- Optionally `make install` or symlink the built binary somewhere stable.

## Phase 5 — Polish & maintenance

- Nicer pill art (rounded rect, hover), fade in/out, position option.
- Track upstream: periodically `git fetch` + rebase `beam-overlay`.
- Note: self-built binary replaces the snap as the client Beam launches.

---

## Risks / notes
- Disk at 95% is the main hazard — don't let `/` fill during build.
- First build can be long; it's a large Qt/C++ app.
- The overlay touches the SDL render + input loop across multiple renderer
  backends; test on the EGL renderer (default on this RX 9060 XT / RADV) first.
- GPL-3.0: keep the fork's source available; Beam stays GPL-3.0 too.

## Quick resume checklist
- [x] Phase 1 toolchain installed (2026-10-04, disk had 40 GB free)
- [x] Phase 2 baseline built; pairing copied from snap config to
      `~/.config/Moonlight Game Streaming Project/Moonlight.conf`
- [x] branch `beam-overlay` (commit b788c11)
- [x] Phase 3 overlay pill — built, streams cleanly on EGL/VAAPI;
      **click-through not yet verified by hand**
- [x] Phase 4 Beam auto-uses `~/beam-moonlight/app/moonlight`; Settings has
      binary path + "In-stream Beam button" switch (BEAM_HIDE_PILL)
- [ ] Hand-test: pill click, menu items, Ctrl+Alt+Shift+B in Game mode,
      fullscreen toggle re-placement
- [ ] Phase 5 polish (fade, position option, upstream rebase)

## Phase 3 as built (2026-10-04)
- `OverlayControls` type; `OverlayManager::updateOverlaySurface()` (custom
  surface, kept and re-pushed to new renderers), `placeTopCenterOverlay()`
  (renderers call it; records drawn rect), `windowPointToOverlay()` (scales
  window points to drawable px for hit-testing).
- `app/streaming/input/controls.cpp`: layout/drawing (Ubuntu-M font, lime
  #9ae600 on #1b1b1b), hit-test, menu state. Items call existing KeyCombo
  handlers. Pill clickable in Desktop mouse mode or when uncaptured; in Game
  mode use Ctrl+Alt+Shift+B, which releases relative capture while the menu is
  open and restores it on close. Clicks on pill/menu never reach the host;
  held buttons are released to the host when the menu opens.
- Only enabled on Linux (Win/mac renderers have no placement branch).
- Rebuild: `cd ~/beam-moonlight && make -j$(nproc) release`
