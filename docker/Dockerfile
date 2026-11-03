# Crawler + a virtual screen you can watch over VNC.
#
# Chromium and its driver come from Debian, so their versions always match —
# a mismatched chromedriver is the usual cause of "session not created".
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    SCREEN=1600x1000x24 \
    PYTHONUNBUFFERED=1 \
    FIND_FORMS_CHROME_BINARY=/usr/bin/chromium \
    FIND_FORMS_CHROMEDRIVER=/usr/bin/chromedriver \
    # Chromium cannot use its sandbox inside a container without extra
    # privileges, and /dev/shm is small by default (compose raises it, but this
    # keeps a plain `docker run` from crashing tabs).
    FIND_FORMS_CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage"

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium chromium-driver \
        xvfb x11vnc fluxbox xdotool x11-utils feh \
        novnc websockify \
        python3 python3-pip \
        fonts-liberation fonts-dejavu-core fonts-noto-color-emoji \
        ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# Fonts matter: a missing font changes text size, and the crawler records the
# rendered width and height of every form.

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# AWS RDS's certificate authorities, so a connection to RDS can verify it is
# talking to the real server: add
#   ?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem
# to FIND_FORMS_DATABASE_URL. Readable by the crawler user (ADD from a URL
# would otherwise leave it 600, root's).
ADD --chmod=644 https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
    /etc/ssl/certs/rds-global-bundle.pem

# noVNC expects to be opened at vnc.html; serve it as the index instead.
RUN ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# X puts its socket here; pre-create it so the non-root user does not trip the
# "euid != 0" warning on every start.
RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

RUN useradd -ms /bin/bash crawler
# fluxbox sets the wallpaper through fbsetbg, which pops an error dialog onto
# the screen if it cannot find a setter. feh is that setter, and gives the
# screen a plain backdrop so browser windows stand out.
RUN mkdir -p /home/crawler/.fluxbox \
    && printf 'session.screen0.rootCommand: feh --bg-solid #1d2129\nsession.screen0.toolbar.visible: false\n' \
       > /home/crawler/.fluxbox/init \
    && chown -R crawler:crawler /home/crawler/.fluxbox

WORKDIR /app
COPY --chown=crawler:crawler src/ ./src/
COPY --chown=crawler:crawler scripts/ ./scripts/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /app/inputs /app/outputs \
    && chown -R crawler:crawler /app

USER crawler

# The stealth driver, ready at install: a patched copy of Debian's chromedriver
# in undetected_chromedriver's cache, so it is built for this image's CPU
# whatever the host. The library's own download is Google's x86-64 Linux
# build only, which dies at once in the arm64 image an Apple Silicon Mac
# builds. Same function as every crawl calls, which then finds it in place.
RUN cd /app/src && python3 -c "import argparse; from crawler.browser import prepare_stealth_driver; \
prepare_stealth_driver(argparse.Namespace(stealth=True))" \
    && test -x /home/crawler/.local/share/undetected_chromedriver/undetected_chromedriver

EXPOSE 5900 6080

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
# No arguments: bring the screen up and wait, so you can connect and then run
# crawls yourself with `docker compose exec`.
CMD ["sleep", "infinity"]
