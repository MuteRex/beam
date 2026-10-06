#!/bin/bash
# Serve beam-virtual-display.sh to a host machine and print the command to run
# there. The command checks the file's SHA-256 (served alongside it) before
# running it as root, so a corrupted or swapped download is refused instead of
# executed. Over Tailscale the transfer itself is encrypted and authenticated;
# the hash file keeps the pasted command short, so a mangled paste fails safe.
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

# Serve only this file and its hash, not the whole directory
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp "$dir/$file" "$tmp/"
(cd "$tmp" && sha256sum "$file" > "$file.sha256")
sum="$(cut -d' ' -f1 "$tmp/$file.sha256")"

echo "On the host, run:"
echo
echo "  cd /tmp && curl -fsSO http://$addr:$port/$file -O http://$addr:$port/$file.sha256 && sha256sum -c $file.sha256 && sudo bash $file install"
echo
echo "It should print \"$file: OK\". SHA-256 starts ${sum:0:8}, ends ${sum: -8}."
echo
echo "Serving on $addr:$port (Ctrl+C to stop)…"
python3 -m http.server "$port" --bind "$addr" --directory "$tmp"
