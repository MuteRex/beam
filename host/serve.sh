#!/bin/bash
# Serve beam-virtual-display.sh to a host machine and print the command to run
# there. The command checks the file's SHA-256 before running it as root, so a
# tampered download is refused instead of executed.
#
#   bash host/serve.sh            # serve on this machine's Tailscale IP
#   bash host/serve.sh 192.168.x  # or on a specific address
#
# Prefer the Tailscale IP: that traffic is encrypted, plain LAN HTTP is not.
set -euo pipefail

dir="$(cd "$(dirname "$0")" && pwd)"
file="beam-virtual-display.sh"
port=8765
addr="${1:-$(tailscale ip -4 2>/dev/null | head -1)}"
[ -n "$addr" ] || { echo "No Tailscale IP; pass an address to serve on." >&2; exit 1; }

sum="$(sha256sum "$dir/$file" | cut -d' ' -f1)"
# Serve only this one file, not the whole directory
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp "$dir/$file" "$tmp/"

echo "On the host, run:"
echo
echo "  curl -fsSo /tmp/bvd.sh http://$addr:$port/$file && echo '$sum  /tmp/bvd.sh' | sha256sum -c && sudo bash /tmp/bvd.sh install"
echo
echo "Serving on $addr:$port (Ctrl+C to stop)…"
python3 -m http.server "$port" --bind "$addr" --directory "$tmp"
