# Bootstrap: Drawing Language Editor on Hetzner CX22 / Debian 13

One-time server setup for `editor.drawlang.com`. After this runs, every
push to `main` on GitHub is picked up automatically within ~2 minutes.

**Target server:** Hetzner Cloud CX22, Debian 13 (Trixie), `65.109.134.47`
**Primary domain:** `editor.drawlang.com` → A record pointing at that IP
**Legacy domain (301 redirect):** `editor.beyondpurdue.com` → same IP
**Repo:** `https://github.com/BeyondPurdue/drawlang-editor` (public)

---

## 0. Prerequisites (confirm before starting)

- [x] DNS A record for `editor.drawlang.com` → `65.109.134.47`
- [x] DNS A record for `editor.beyondpurdue.com` → `65.109.134.47` (kept for legacy 301 redirect)
- [x] SSH access to the server as `root`
- [ ] DNS propagated (`dig +short editor.drawlang.com` returns `65.109.134.47`)

If DNS is not yet propagated, everything below still works — you just have
to wait for propagation before Caddy can issue the TLS cert (Step 8).

---

## 1. SSH in and update the base system

```bash
ssh root@65.109.134.47

apt-get update
apt-get -y full-upgrade
apt-get -y install \
    ca-certificates curl gnupg lsb-release git \
    python3 python3-venv python3-pip \
    ghostscript \
    ufw fail2ban \
    debian-keyring debian-archive-keyring apt-transport-https \
    logrotate

# Verify Python 3.13 is present on Debian 13:
python3 --version   # expect: Python 3.13.x
```

---

## 2. Install Caddy (official Debian repo)

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg

curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list

apt-get update
apt-get -y install caddy

# Caddy installs and auto-starts; we'll overwrite its Caddyfile in Step 8.
```

---

## 3. Firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
```

---

## 4. Fail2ban (SSH brute-force protection)

```bash
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
EOF

systemctl enable --now fail2ban
systemctl status fail2ban --no-pager | head -10
```

---

## 5. Clone the repo into /var/www

```bash
mkdir -p /var/www
cd /var/www
git clone https://github.com/BeyondPurdue/drawlang-editor.git
cd drawlang-editor

# Own everything by www-data so the deploy script can pull as that user
chown -R www-data:www-data /var/www/drawlang-editor
```

---

## 6. Create the Python venv and install the editor

```bash
sudo -u www-data python3 -m venv /var/www/drawlang-editor/venv

sudo -u www-data /var/www/drawlang-editor/venv/bin/pip install --upgrade pip
sudo -u www-data /var/www/drawlang-editor/venv/bin/pip install \
    -e "/var/www/drawlang-editor[editor]"

# Smoke test — should print the app object and route count
cd /var/www/drawlang-editor/editor
sudo -u www-data /var/www/drawlang-editor/venv/bin/python -c \
    "from app.main import app; print('OK', len(app.routes), 'routes')"
```

Expected output: `OK 13 routes`

---

## 7. Data directory (SQLite lives here)

```bash
mkdir -p /var/www/drawlang-editor/data
chown www-data:www-data /var/www/drawlang-editor/data
chmod 750 /var/www/drawlang-editor/data
```

---

## 8. Install the systemd units, deploy script, and Caddyfile

```bash
cd /var/www/drawlang-editor

# systemd units
cp deploy/drawlang-editor.service   /etc/systemd/system/drawlang-editor.service
cp deploy/drawlang-deploy.service   /etc/systemd/system/drawlang-deploy.service
cp deploy/drawlang-deploy.timer     /etc/systemd/system/drawlang-deploy.timer

# Deploy script
cp deploy/deploy-drawlang.sh /usr/local/bin/deploy-drawlang
chmod +x /usr/local/bin/deploy-drawlang

# Caddyfile
cp deploy/Caddyfile /etc/caddy/Caddyfile

systemctl daemon-reload

# Start the editor
systemctl enable --now drawlang-editor.service
systemctl status drawlang-editor.service --no-pager | head -15

# Enable the 2-minute pull-and-restart timer
systemctl enable --now drawlang-deploy.timer
systemctl list-timers drawlang-deploy.timer --no-pager

# Reload Caddy so it re-reads the new config
systemctl reload caddy
systemctl status caddy --no-pager | head -15
```

At this point:
- The editor is running on `127.0.0.1:8765`.
- Caddy is reverse-proxying `https://editor.drawlang.com` → the editor,
  and `https://editor.beyondpurdue.com` → 301 permanent redirect to the
  primary hostname (preserves path + query).
- Once DNS resolves and the first HTTPS request comes in, Caddy will
  auto-provision a Let's Encrypt cert for each hostname. Watch it happen:

```bash
journalctl -u caddy -f
# In another shell:  curl -v https://editor.drawlang.com/examples
```

### Gotcha: per-hostname log files

The Caddyfile writes an access log to `/var/log/caddy/<hostname>.log`.
Caddy runs as the unprivileged `caddy` user and can only write to files
it owns. When you **add a new hostname** or **rename an existing one**
(as with the drawlang.com cutover), pre-create the log file before
reloading Caddy:

```bash
sudo touch /var/log/caddy/editor.drawlang.com.log
sudo chown caddy:caddy /var/log/caddy/editor.drawlang.com.log
sudo chmod 640 /var/log/caddy/editor.drawlang.com.log
sudo systemctl reload caddy
```

Symptom if you forget: `caddy validate` says `Valid configuration` but
`systemctl reload caddy` fails with `open /var/log/caddy/<host>.log:
permission denied` in the journal. The old config keeps running — the
reload safely refuses to apply the new one.

---

## 9. Verify end-to-end

```bash
# From the server (bypasses DNS):
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8765/examples
# HTTP 200

# Once DNS resolves — primary hostname:
curl -sS -o /dev/null -w "HTTP %{http_code}\n" https://editor.drawlang.com/examples
# HTTP 200

# Legacy hostname — must return a 301 to the primary:
curl -sSI https://editor.beyondpurdue.com/examples | head -3
# HTTP/2 301
# location: https://editor.drawlang.com/examples
```

Open `https://editor.drawlang.com` in a browser. The editor should
load with the full template library (2,460 items) and all endpoints
should work (render, save, examples, reference, PDF export).

---

## 10. Watch the auto-deploy in action

```bash
# Live tail of the deploy timer's fires:
journalctl -u drawlang-deploy.service -f

# Next scheduled run:
systemctl list-timers drawlang-deploy.timer --no-pager
```

Push any change to `main` on GitHub and within ~2 minutes you should see
a log entry like `Update: 70f7f42 → 9d1e2c8` followed by
`Deployed 9d1e2c8 — service active`.

---

## 11. Useful ongoing commands

| Task | Command |
|------|---------|
| Restart the editor by hand | `systemctl restart drawlang-editor.service` |
| Trigger a deploy immediately | `systemctl start drawlang-deploy.service` |
| Tail editor logs | `journalctl -u drawlang-editor.service -f` |
| Tail deploy logs | `journalctl -u drawlang-deploy.service -f` |
| Check disk / DB size | `du -sh /var/www/drawlang-editor/data` |
| Backup the DB | `sqlite3 /var/www/drawlang-editor/data/drawings.db ".backup /root/drawings-$(date +%F).db"` |
| Renew Caddy manually (rare) | `systemctl reload caddy` |

---

## 12. When to size up

The current CX22 (2 vCPU / 4 GB) with 4 uvicorn workers comfortably
handles ~50 concurrent editors. Upgrade paths in order:

1. **CX32** (4 vCPU / 8 GB, ~€6.80/mo) — bump `--workers 4` → `--workers 8`
   in `drawlang-editor.service`, no other changes needed.
2. **Add PostgreSQL** — when self-registration lands and concurrent writes
   exceed ~50/sec. Swap `editor/app/storage.py` for a `psycopg` version.
3. **Add Redis + RQ** — when `/export/pdf` traffic warrants a job queue.

---

## 13. Troubleshooting

**Editor won't start:** `journalctl -u drawlang-editor.service --no-pager -n 50`

**Deploy timer fires but nothing changes:** Check
`/usr/local/bin/deploy-drawlang` exists and is executable; check
`git status` in `/var/www/drawlang-editor` as `www-data`.

**Caddy can't get a cert:** `journalctl -u caddy --no-pager -n 50` — usually
DNS hasn't propagated yet. Wait, then `systemctl reload caddy`.

**HTTP 502 from Caddy:** Editor service is down. `systemctl status
drawlang-editor.service`.

**Disk fills up:** Check `/var/log/caddy/` and `/var/www/drawlang-editor/data/`.
Caddy log rotation is configured to 10 MB × 5 files.
