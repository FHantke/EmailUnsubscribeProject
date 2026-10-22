#!/bin/bash
# Bring up a virtual screen, a window manager and two ways to watch it, then
# run whatever command was passed. Every piece is optional to the crawl itself:
# if VNC fails the crawl still runs, it just cannot be watched.
set -euo pipefail

cleanup() { pkill -P $$ || true; }
trap cleanup EXIT

Xvfb "$DISPLAY" -screen 0 "$SCREEN" -nolisten tcp &
for _ in $(seq 100); do
    xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break
    sleep 0.1
done
xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 || { echo "Xvfb did not start on $DISPLAY" >&2; exit 1; }

fluxbox >/dev/null 2>&1 &          # so browser windows can be moved and raised

# A password is used when VNC_PASSWORD is set. Without one the port is open to
# anyone who can reach it, which is why compose binds it to localhost only.
if [ -n "${VNC_PASSWORD:-}" ]; then
    mkdir -p "$HOME/.vnc"
    x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1
    auth=(-rfbauth "$HOME/.vnc/passwd")
else
    auth=(-nopw)
fi
x11vnc -display "$DISPLAY" -forever -shared -repeat -rfbport 5900 "${auth[@]}" -quiet >/dev/null 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

echo "screen $SCREEN on $DISPLAY | VNC :5900 | browser http://localhost:6080/" >&2
exec "$@"
