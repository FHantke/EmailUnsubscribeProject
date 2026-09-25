#!/bin/bash
# Provision a receive-only Postfix MX for the study (Layout A: single disk).
# Idempotent: safe to rerun. Change configuration HERE, not in /etc/postfix,
# because every run regenerates the Postfix files.
#
#   sudo STUDY_DOMAIN=yourdomain.tld ./provision.sh
#
# Optional: MX_HOST (default mx.$STUDY_DOMAIN), ADMIN_USER (default $SUDO_USER
# or ubuntu), MAILBOX_PATTERN (default news[0-9]+).
set -euo pipefail

: "${STUDY_DOMAIN:?set STUDY_DOMAIN, e.g. STUDY_DOMAIN=yourdomain.tld}"
MX_HOST=${MX_HOST:-mx.$STUDY_DOMAIN}
ADMIN_USER=${ADMIN_USER:-${SUDO_USER:-ubuntu}}
MAILBOX_PATTERN=${MAILBOX_PATTERN:-'news[0-9]+'}
STATE=/var/lib/mailstore-provision

log()  { echo "[provision] $*"; }
warn() { echo "[provision] WARNING: $*" >&2; }
die()  { echo "[provision] ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"
for v in "$STUDY_DOMAIN" "$MX_HOST"; do
  [[ $v =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || die "invalid name: $v"
done
DOMAIN_RE=${STUDY_DOMAIN//./\\.}
mkdir -p "$STATE"

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
apt_get() { apt-get -o DPkg::Lock::Timeout=600 \
  -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"; }

# --- Step 2: no unscheduled updates -------------------------------------
log "disabling automatic updates"
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
systemctl stop apt-daily.service apt-daily-upgrade.service unattended-upgrades.service 2>/dev/null || true
systemctl mask apt-daily.service apt-daily-upgrade.service >/dev/null
apt_get purge -y unattended-upgrades >/dev/null 2>&1 || true
mkdir -p /etc/apt/apt.conf.d /etc/needrestart/conf.d
printf 'APT::Periodic::Update-Package-Lists "0";\nAPT::Periodic::Unattended-Upgrade "0";\n' \
  > /etc/apt/apt.conf.d/20auto-upgrades
echo "\$nrconf{restart} = 'l';" > /etc/needrestart/conf.d/50-manual.conf
if command -v snap >/dev/null; then
  timeout 300 snap wait system seed.loaded 2>/dev/null || true
  snap refresh --hold >/dev/null 2>&1 || warn "could not hold snap refreshes"
fi

# --- Step 3: packages ---------------------------------------------------
log "installing packages"
apt_get update -q
if [ ! -f "$STATE/baseline-upgraded" ]; then
  apt_get -y upgrade -q
  touch "$STATE/baseline-upgraded"
fi
echo 'postfix postfix/main_mailer_type select No configuration' | debconf-set-selections
apt_get install -y -q postfix rsyslog rsync swaks

# --- Step 4: swap -------------------------------------------------------
if [ ! -f /swapfile ]; then
  log "creating swap"
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null
fi
swapon --show | grep -q /swapfile || swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness = 10' > /etc/sysctl.d/60-swappiness.conf
sysctl --system >/dev/null

# --- Step 5: storage user and data store (Layout A) ---------------------
log "preparing /srv/mail"
id mailstore >/dev/null 2>&1 || useradd --system --no-create-home \
  --home-dir /nonexistent --shell /usr/sbin/nologin mailstore
if id "$ADMIN_USER" >/dev/null 2>&1; then
  usermod -aG mailstore,adm "$ADMIN_USER"
else
  warn "user $ADMIN_USER not found; archive read access not granted"
fi
mkdir -p /srv/mail
chown mailstore:mailstore /srv/mail
chmod 2750 /srv/mail
if [ -e /srv/mail/.mailstore.paused ]; then
  warn "delivery is paused (.mailstore.paused exists); leaving it paused"
elif [ ! -f /srv/mail/.mailstore ]; then
  install -m 0440 -o mailstore -g mailstore /dev/null /srv/mail/.mailstore
fi

# --- Step 6: handler ----------------------------------------------------
log "installing handler"
install -d -m 0755 /opt/mailstore
cat > /opt/mailstore/handler.py.new <<'HANDLER_EOF'
#!/usr/bin/python3
"""Persist-only delivery handler for Postfix pipe(8).

Postfix runs this once per recipient (destination_recipient_limit = 1),
with the message on stdin and envelope data as key=value arguments:

    class=primary queue_id=... sender=... original_recipient=...
    recipient=... client_address=... client_hostname=... client_helo=...
    size=...

It writes the message (.eml) and a metadata sidecar (.json) to
/srv/mail/<class>/YYYY/MM/DD/, durably, and exits.

Exit status contract with Postfix:
    0   delivered; Postfix removes the message from its queue
    75  EX_TEMPFAIL; Postfix keeps the message queued and retries
pipe(8) treats ANY other exit status as a permanent failure, so every
failure path in this file must end in 75.

Delivery is at-least-once: if a failure happens after the .eml is
published but before Postfix records success, the retry writes a second
copy under a new name. Deduplicate at analysis time on
(queue_id, envelope_recipient, sha256).
"""

import datetime
import hashlib
import json
import os
import sys
import uuid

ROOT = "/srv/mail"
TMP = os.path.join(ROOT, "tmp")
SENTINEL = os.path.join(ROOT, ".mailstore")
CLASSES = ("primary", "quarantine", "admin")
EXPECTED_KEYS = (
    "class",
    "queue_id",
    "sender",
    "original_recipient",
    "recipient",
    "client_address",
    "client_hostname",
    "client_helo",
    "size",
)
HANDLER_VERSION = "2"
EX_TEMPFAIL = 75
CHUNK = 1 << 16


def parse_args(argv):
    """Parse key=value arguments. Values may be empty (null sender)."""
    args = {}
    for item in argv:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"malformed argument {item!r}")
        args[key] = value
    missing = [k for k in EXPECTED_KEYS if k not in args]
    if missing:
        raise ValueError(f"missing arguments: {', '.join(missing)}")
    if args["class"] not in CLASSES:
        raise ValueError(f"unknown class {args['class']!r}")
    return args


def fsync_path(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_dir(path):
    """Create path and any missing parents, fsyncing each new entry."""
    missing = []
    probe = path
    while not os.path.isdir(probe):
        missing.append(probe)
        probe = os.path.dirname(probe)
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o750)
        except FileExistsError:
            pass  # a concurrent delivery created it first
        fsync_path(os.path.dirname(directory))


def deliver(args):
    # The data store is "available" only if its sentinel file exists.
    # With a separate data volume, the sentinel lives on that volume, so it
    # is absent whenever the volume isn't mounted and mail would otherwise
    # land on the root disk hidden under the mount point. On a single disk,
    # renaming the sentinel is a deliberate way to pause delivery. Either
    # way the result is a deferral, never a write to the wrong place.
    if not os.path.isfile(SENTINEL):
        raise RuntimeError(f"{SENTINEL} missing: data store not available")

    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    # Unique per delivery, never derived from content: the same message
    # delivered to two aliases must produce two files.
    base = f"{stamp}-{args['queue_id']}-{uuid.uuid4().hex}"
    final_dir = os.path.join(
        ROOT, args["class"], now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
    )
    ensure_dir(TMP)
    ensure_dir(final_dir)

    tmp_eml = os.path.join(TMP, base + ".eml")
    tmp_json = os.path.join(TMP, base + ".json")

    digest = hashlib.sha256()
    written = 0
    stdin = sys.stdin.buffer
    with open(tmp_eml, "xb") as out:
        while True:
            chunk = stdin.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)
        out.flush()
        os.fsync(out.fileno())

    meta = {
        "handler_version": HANDLER_VERSION,
        "received_utc": now.isoformat(),
        "class": args["class"],
        "queue_id": args["queue_id"],
        "envelope_sender": args["sender"],
        "envelope_recipient": args["recipient"],
        "original_recipient": args["original_recipient"],
        "client_address": args["client_address"],
        "client_hostname": args["client_hostname"],
        "client_helo": args["client_helo"],
        "postfix_size": args["size"],
        "bytes_written": written,
        "sha256": digest.hexdigest(),
        "file": base + ".eml",
    }
    with open(tmp_json, "x", encoding="utf-8") as out:
        json.dump(meta, out, ensure_ascii=False, indent=1, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())

    os.chmod(tmp_eml, 0o440)
    os.chmod(tmp_json, 0o440)
    fsync_path(TMP)

    # Publish the message before its sidecar, so a .json never exists
    # without the .eml it describes. Both paths are on the same
    # filesystem, so each rename is atomic.
    os.rename(tmp_eml, os.path.join(final_dir, base + ".eml"))
    os.rename(tmp_json, os.path.join(final_dir, base + ".json"))
    fsync_path(final_dir)
    fsync_path(TMP)


def main():
    os.umask(0o027)
    deliver(parse_args(sys.argv[1:]))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # anything at all: defer, never bounce
        try:
            sys.stderr.write(f"deferred by handler: {exc!r}\n")
            sys.stderr.flush()
        except BaseException:
            pass
        os._exit(EX_TEMPFAIL)
    sys.exit(0)
HANDLER_EOF
install -m 0755 -o root -g root /opt/mailstore/handler.py.new /opt/mailstore/handler.py
rm -f /opt/mailstore/handler.py.new
rc=0; sudo -u mailstore /opt/mailstore/handler.py </dev/null 2>/dev/null || rc=$?
[ "$rc" -eq 75 ] || die "handler self-test returned $rc, expected 75"

# --- Step 7: Postfix ----------------------------------------------------
log "configuring postfix"
if [ -d "/etc/letsencrypt/live/$MX_HOST" ]; then
  TLS_FILES="/etc/letsencrypt/live/$MX_HOST/privkey.pem, /etc/letsencrypt/live/$MX_HOST/fullchain.pem"
else
  TLS_FILES="/etc/ssl/private/ssl-cert-snakeoil.key, /etc/ssl/certs/ssl-cert-snakeoil.pem"
fi

cat > /etc/postfix/main.cf <<'MAINCF_EOF'
# GENERATED by provision.sh -- edit the script, not this file.
compatibility_level = 3.6
myhostname = __MX_HOST__
myorigin = $myhostname
mydestination = $myhostname, localhost
inet_interfaces = all
inet_protocols = ipv4
smtpd_banner = $myhostname ESMTP
biff = no
append_dot_mydomain = no
alias_maps = hash:/etc/aliases
alias_database = hash:/etc/aliases

virtual_mailbox_domains = __DOMAIN__
virtual_mailbox_maps = regexp:/etc/postfix/study_accept
transport_maps = regexp:/etc/postfix/study_transport
primary_destination_recipient_limit = 1
quarantine_destination_recipient_limit = 1
admin_destination_recipient_limit = 1
recipient_delimiter =

relayhost =
default_transport = error:outbound delivery disabled on this host
relay_transport = error:outbound delivery disabled on this host
mynetworks = 127.0.0.0/8
smtpd_relay_restrictions = reject_unauth_destination
smtpd_recipient_restrictions =
disable_vrfy_command = yes
smtpd_forbid_bare_newline = normalize
smtpd_forbid_unauth_pipelining = no

soft_bounce = yes
maximal_queue_lifetime = 30d
bounce_queue_lifetime = 30d
minimal_backoff_time = 300s
maximal_backoff_time = 1800s
delay_warning_time = 0h

message_size_limit = 104857600
mailbox_size_limit = 0
queue_minfree = 2147483648
default_process_limit = 25
smtpd_client_connection_count_limit = 10

smtpd_tls_security_level = may
smtpd_tls_chain_files = __TLS_FILES__
smtpd_tls_loglevel = 1
smtpd_tls_received_header = yes
smtpd_tls_session_cache_database = btree:${data_directory}/smtpd_scache
MAINCF_EOF
sed -i -e "s|__MX_HOST__|$MX_HOST|" -e "s|__DOMAIN__|$STUDY_DOMAIN|" \
  -e "s|__TLS_FILES__|$TLS_FILES|" /etc/postfix/main.cf
! grep -q '__' /etc/postfix/main.cf || die "unreplaced placeholder in main.cf"

printf '/@%s$/\tOK\n' "$DOMAIN_RE" > /etc/postfix/study_accept
{
  printf '/^(postmaster|abuse)@%s$/\tadmin:\n' "$DOMAIN_RE"
  printf '/^%s(\\+[^@]*)?@%s$/\tprimary:\n' "$MAILBOX_PATTERN" "$DOMAIN_RE"
  printf '/@%s$/\tquarantine:\n' "$DOMAIN_RE"
} > /etc/postfix/study_transport

[ -f /etc/postfix/master.cf ] || cp /usr/share/postfix/master.cf.dist /etc/postfix/master.cf
postconf -M 'primary/unix=primary unix - n n - 8 pipe user=mailstore argv=/opt/mailstore/handler.py class=primary queue_id=${queue_id} sender=${sender} original_recipient=${original_recipient} recipient=${recipient} client_address=${client_address} client_hostname=${client_hostname} client_helo=${client_helo} size=${size}'
postconf -M 'quarantine/unix=quarantine unix - n n - 4 pipe user=mailstore argv=/opt/mailstore/handler.py class=quarantine queue_id=${queue_id} sender=${sender} original_recipient=${original_recipient} recipient=${recipient} client_address=${client_address} client_hostname=${client_hostname} client_helo=${client_helo} size=${size}'
postconf -M 'admin/unix=admin unix - n n - 2 pipe user=mailstore argv=/opt/mailstore/handler.py class=admin queue_id=${queue_id} sender=${sender} original_recipient=${original_recipient} recipient=${recipient} client_address=${client_address} client_hostname=${client_hostname} client_helo=${client_helo} size=${size}'

[ -f /etc/aliases ] || printf 'postmaster: root\n' > /etc/aliases
newaliases
postfix check || die "postfix check failed"

# Newer packaging runs the main instance in postfix.service; older packaging
# used a oneshot wrapper plus postfix@-.service.
if [ "$(systemctl show -p Type --value postfix.service)" = oneshot ]; then
  UNIT=postfix@-.service
else
  UNIT=postfix.service
fi
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null 2>&1
systemctl restart "$UNIT"
sleep 2
ss -ltn '( sport = :25 )' | grep -q LISTEN || die "nothing listening on port 25"

# --- Step 7e: keep mail.log for two years, with stable rotated names ----
LR=/etc/logrotate.d/rsyslog
if [ -f "$LR" ] && ! grep -q dateext "$LR"; then
  sed -i -e 's/^\([[:space:]]*\)rotate 4$/\1rotate 104/' \
         -e 's/^\([[:space:]]*\)weekly$/&\n\1dateext/' "$LR"
fi
grep -q 'rotate 104' "$LR" 2>/dev/null || warn "log retention not extended; edit $LR by hand"

log "done: $UNIT active, port 25 listening, delivering to /srv/mail"
log "TLS: $TLS_FILES"