# Deploying the demo (Michelito)

The public demo runs on a VPS with Docker: the app's image (`michelito demo`, made-up data)
behind Caddy, which adds HTTPS and the security headers. GitHub Actions builds and deploys it on
its own every time CI passes on `main`; if the new version does not answer, the server goes back
to the previous one and the job fails.

In this document `demo.michelito.app` is the default host, `michelito-app/michelito` the repo and
`ghcr.io/michelito-app/michelito` the image; change them if you use others. The server commands
are written for your admin user (with `sudo`) and with absolute paths.

## Architecture

```
visitor ──https (IPv4/IPv6)──▶ Caddy (80/443, Let's Encrypt) ──http──▶ app (michelito demo, :8600)
                               networks "public" + "internal"          only "internal", no internet
                                                                       volume "data" → /data
GitHub Actions
  CI (ci.yml): pytest, ruff, mypy, check_private, check_spanish · lint, typecheck, vitest, build · Playwright
  └─ if it passes on main and the commit is still the tip of main → deploy.yml
       image     → ghcr.io/michelito-app/michelito:<sha> and :latest (and its digest)
       deploy    (environment "demo") → ssh deploy@VPS "<sha> <digest>"  (token on stdin)
                                       → curl https://demo.michelito.app/api/health
```

- **Image** (`Dockerfile`): builds the interface with Node, installs the app with
  `uv sync --frozen --no-dev` and leaves in the final stage only Python and the environment,
  without pip, uv, Node or the source code. It runs as the `michelito` user (uid 10001), only with
  `michelito demo` (`MICHELITO_MODE=demo`: no Gmail, keyring or real data). Template, copies and
  `feedback.db` go in `/data`. Its `HEALTHCHECK` requests `/api/health`.
- **Compose** (`deploy/docker-compose.yml`): the app runs by digest (`image@sha256:…`, what the
  workflow built), without published ports, on the `internal` network (no way out to the
  internet). Both containers have a read-only file system (except their volumes and an in-memory
  `/tmp`), no capabilities (Caddy only the one to open 80/443), `no-new-privileges`, process and
  memory limits (app 512 MB, Caddy 128 MB), and restart on their own. The `public` network has its
  own IPv6 (see "IPv6").
- **Caddy** (`deploy/Caddyfile`): automatic certificate for `$MICHELITO_HOST`, compression, HSTS,
  a strict CSP (everything from the same origin, nothing inline), `X-Content-Type-Options`,
  `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`; it removes `Server` and `Via`. It puts
  in `X-Forwarded-For` the IP of whoever connected (a single hop) and drops the one the client
  sends; the app only trusts it if it comes from the internal network (`MICHELITO_DEMO_PROXIES`),
  and counts the per-IP copy quota with it (only in memory).
- **Deploy** (`deploy/deploy.sh`): it is the *forced command* of the deploy key: that key opens no
  terminal and cannot run anything else. It only accepts `"<sha> sha256:<digest>"` (40 and 64
  hexadecimal characters) or `rollback`, and the GHCR token on stdin. See "What a deploy does".

## 1. The server (once)

An Ubuntu LTS VPS (1 GB of RAM is enough). As root or with `sudo`:

1. A non-root admin user with your key, and SSH with keys only:
   ```bash
   adduser --disabled-password --gecos "" admin
   usermod -aG sudo admin
   # and copy your public key to admin's authorized_keys (ssh-copy-id from your machine)
   # /etc/ssh/sshd_config.d/10-hardening.conf
   #   PasswordAuthentication no
   #   KbdInteractiveAuthentication no
   #   PermitRootLogin no
   systemctl reload ssh
   ```
   (Try logging in with the key from another terminal before closing the root session.)
2. Firewall: `ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable`.
   Careful: the ports Docker publishes do not go through ufw's input rules; here only 80 and 443
   are published, which are open anyway.
3. Automatic security updates: `apt install unattended-upgrades` and
   `dpkg-reconfigure -plow unattended-upgrades`.
4. Docker Engine with the compose plugin, from Docker's official repository
   (docs.docker.com/engine/install/ubuntu). For IPv6, see the next section.
5. DNS: `A` and `AAAA` records for `demo` pointing to the VPS, in Cloudflare in **"DNS only"** mode
   (gray cloud). Caddy needs port 80 or 443 to arrive directly to get the certificate.

### IPv6

With an `AAAA` record, some visitors arrive over IPv6. If Caddy's network were IPv4 only, Docker
would pass those connections through `docker-proxy` and Caddy would see the bridge gateway (a
private IPv4) instead of the visitor: everyone on IPv6 would share a single copy quota. That is why
the compose file's `public` network has `enable_ipv6: true` and a fixed ULA subnet
(`MICHELITO_NET6`, by default `fd4d:6963:6865:6c00::/64`): that way Docker publishes 443 on IPv6
with `ip6tables` rules (DNAT), which keep the source IP.

On the daemon side nothing is needed with Docker 27 or newer: `ip6tables` is enabled by default
(Docker's documentation, "Use IPv6 networking"). Just check nobody turned it off:

```bash
sudo cat /etc/docker/daemon.json 2>/dev/null   # it must not say "ip6tables": false
```

Optional: `"userland-proxy": false` in `/etc/docker/daemon.json` (and
`sudo systemctl restart docker`) removes `docker-proxy` entirely; if something were misconfigured,
IPv6 connections would fail instead of arriving with the wrong IP. It is not needed with the
compose file's IPv6 network.

Verification, after the first deploy:

```bash
# From a machine with IPv6 (outside the VPS):
curl -6 -fsS https://demo.michelito.app/api/health

# On the VPS: IPv6 443 goes to the IPv6 of Caddy's container (not to a 172.x IPv4):
pgrep -a docker-proxy | grep -- '-host-port 443'   # the "::" line must say -container-ip fd4d:…
```

The app does not log IPs (on purpose: not even in the log). To check which IP reaches Caddy (and
therefore the app, which takes that single hop), look at the open connections inside Caddy's
container while you hold one open from outside:

```bash
# Outside, keep a connection open for a few seconds:
openssl s_client -connect demo.michelito.app:443 -6 -quiet </dev/null & sleep 10; kill %1
# On the VPS, at the same time:
sudo nsenter -t "$(sudo docker inspect -f '{{.State.Pid}}' michelito-caddy-1)" -n ss -tn 'sport = :443'
```

The "Peer Address" column must show your public IPv6, not `fd4d:…::1` or `172.x.x.1` (the bridge
gateway). Tested locally (Docker 27): with the IPv6 network Caddy sees the real IPv6 and IPv4 and
IPv6 visitors have separate quotas; without it, IPv6 connections arrive as the IPv4 gateway.

### Deploy user and key

```bash
# On the server: the user GitHub Actions uses (it can use docker, nothing else).
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
```

Careful: being in the `docker` group is equivalent to root on the machine. That is why that user's
key can only run `deploy.sh` (forced command + `restrict`); do not give it any other key.

```bash
# On your machine: a key only for this, without a passphrase (GitHub keeps it as a secret).
ssh-keygen -t ed25519 -N "" -C github-deploy -f ./michelito-deploy
```

## 2. First start on the server

Copy `deploy/docker-compose.yml`, `deploy/Caddyfile` and `deploy/deploy.sh` from the repository
(for example with `scp` to your admin user) and, on the server, from the folder where they landed:

```bash
sudo install -d -o deploy -g deploy -m 750 /opt/michelito
sudo install -o deploy -g deploy -m 644 docker-compose.yml Caddyfile /opt/michelito/
sudo install -o deploy -g deploy -m 750 deploy.sh /opt/michelito/
sudo -u deploy tee /opt/michelito/.env >/dev/null <<'EOF'
MICHELITO_HOST=demo.michelito.app
MICHELITO_IMAGE=ghcr.io/michelito-app/michelito
GHCR_USER=michelito-app
EOF
sudo chmod 600 /opt/michelito/.env

# The deploy key, tied to deploy.sh:
DEPLOY_HOME=$(getent passwd deploy | cut -d: -f6)
sudo install -d -o deploy -g deploy -m 700 "$DEPLOY_HOME/.ssh"
echo 'command="/opt/michelito/deploy.sh",restrict ssh-ed25519 AAAA…(contents of michelito-deploy.pub)… github-deploy' \
  | sudo -u deploy tee "$DEPLOY_HOME/.ssh/authorized_keys" >/dev/null
sudo chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
```

- `Caddyfile` and `docker-compose.yml` must be **644**, not 640: Caddy runs with `cap_drop: [ALL]`
  (so not even its root can bypass file permissions) and could not read a 640 `Caddyfile`
  mounted into the container. `.env` stays **600** (only `deploy` reads it; compose reads it as
  `deploy`).
- The server's `.env` keys:

  | Key | Who writes it | What |
  |-----|---------------|------|
  | `MICHELITO_HOST` | you (required) | the public host (`demo.michelito.app`) |
  | `MICHELITO_IMAGE` | you (required) | the image without a tag (`ghcr.io/michelito-app/michelito`) |
  | `GHCR_USER` | you (required) | the user `deploy.sh` logs in to GHCR with |
  | `MICHELITO_TAG` | `deploy.sh` | the sha of the running version |
  | `MICHELITO_DIGEST` | `deploy.sh` | the digest of its image |
  | `MICHELITO_NET` | you (optional) | the internal network's subnet (`172.30.53.0/24`) |
  | `MICHELITO_NET6` | you (optional) | the public network's IPv6 subnet (`fd4d:6963:6865:6c00::/64`) |
  | `MICHELITO_REPO` | you (optional) | the demo's "Open source" link |

- `MICHELITO_TAG` and `MICHELITO_DIGEST` (the running version) are **not** written by hand:
  `deploy.sh` adds them to `.env`. Until there is a first deploy, `docker compose` refuses to
  start.
- `GHCR_USER`: any GitHub name works with the workflow's token; use the organization's.
- Change `MICHELITO_NET` and `MICHELITO_NET6` if they clash with another network on the server.
- If the GHCR package is private, the workflow's token works anyway: it goes on stdin, `deploy.sh`
  uses it with a temporary `DOCKER_CONFIG` and logs out (`docker logout`) when done; the token
  expires with the job.

The `known_hosts` for GitHub: on your machine, `ssh-keyscan -t ed25519 <vps-ip-or-host>`, and
compare the fingerprint with the server's (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`,
from the provider's console) before saving it as a secret.

### Upgrading from the Spanish layout

A server set up before the English rename (one time, in this order):

1. Back up the feedback store **by hand, while the old app is still running**, then stop the old
   stack **with the old compose file**, before installing the new files. `deploy.sh` cannot make
   this backup: after the `down` there is no running app to read it from. The compose networks
   were renamed (`interna`/`publica` → `internal`/`public`) and keep the same subnets, so the new <!-- spanish-data -->
   file cannot start while the old networks exist. The `down` has no `-v`: the volumes
   `michelito_datos` and `michelito_caddy_datos` keep their pinned names and the new file reuses <!-- spanish-data -->
   them, with the feedback and Caddy's certificates.

   ```bash
   cd /opt/michelito
   sudo -u deploy mkdir -p backups
   sudo -u deploy sh -c 'docker compose exec -T app python -c "import sqlite3, sys; s = sqlite3.connect(\"file:/datos/opiniones.db?mode=ro\", uri=True); d = sqlite3.connect(\"/tmp/b.db\"); s.backup(d); d.close(); sys.stdout.buffer.write(open(\"/tmp/b.db\", \"rb\").read())" > backups/pre-rename-feedback.db' # spanish-data
   head -c 15 backups/pre-rename-feedback.db; echo   # must print: SQLite format 3
   sudo -u deploy docker compose --project-directory /opt/michelito down
   ```

2. Install the new `docker-compose.yml` and `Caddyfile` (644) and `deploy.sh` (750) as above.
   **Keep the existing `.env`**: do not write it again with `tee` (it holds `MICHELITO_TAG`,
   `MICHELITO_DIGEST` and your settings); only rename its keys, if present:
   `MICHELITO_RED` → `MICHELITO_NET` and `MICHELITO_RED6` → `MICHELITO_NET6`. <!-- spanish-data -->
   `deploy.sh` has a new path: remove the old script and change the forced command in
   `authorized_keys` to `command="/opt/michelito/deploy.sh",restrict ssh-ed25519 … github-deploy`.
3. Deploy (re-run the workflow or push to `main`). On its first start the app migrates the old
   feedback store `opiniones.db` into `feedback.db` (the old file stays untouched; if the <!-- spanish-data -->
   migration fails nothing is left half-written and it is retried on the next start). Old backups
   stay in `respaldos/`; new ones go to `backups/`. <!-- spanish-data -->

The upgrade is **one way**: an image from before the rename does not work with the new compose
file (it reads other variables and another data path, so it would start and pass the health check
while writing to a throwaway volume). `deploy.sh` therefore never goes back past the rename: until
its first successful deploy it does not take the running (pre-rename) version as a fallback or a
`rollback` target, ignores the old previous-version file, and `rollback` refuses with a message.
After that deploy there is no previous version yet (`previous-tag` is only written by the next
deploy); the pre-rename image is kept on the server. To return to the old layout you would have
to reinstall the old files and the old `deploy.sh` by hand.

## 3. GitHub: environment, secrets and variables

**Required**: the `demo` environment only allows the `main` branch (Settings → Environments → demo
→ Deployment branches → "Selected branches" → `main`), and the VPS secrets go **only** in that
environment, never at repository level: that way no other workflow or branch can read them.

```bash
R=michelito-app/michelito
gh api -X PUT "repos/$R/environments/demo" \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST "repos/$R/environments/demo/deployment-branch-policies" -f name=main -f type=branch

gh secret set VPS_HOST --env demo -R "$R" --body '<vps-ip-or-host>'
gh secret set VPS_USER --env demo -R "$R" --body 'deploy'
gh secret set VPS_SSH_KEY --env demo -R "$R" < ./michelito-deploy
gh secret set VPS_KNOWN_HOSTS --env demo -R "$R" < ./known_hosts_vps
gh variable set MICHELITO_HOST -R "$R" --body 'demo.michelito.app'
```

| Name | Where | What |
|------|-------|------|
| `VPS_HOST` | `demo` secret | IP or name of the VPS (the same one that goes in `VPS_KNOWN_HOSTS`) |
| `VPS_USER` | `demo` secret | `deploy` |
| `VPS_SSH_KEY` | `demo` secret | the **private** key `michelito-deploy` |
| `VPS_KNOWN_HOSTS` | `demo` secret | the verified `ssh-keyscan` line |
| `MICHELITO_HOST` | repo variable | `demo.michelito.app` (it is the default if it does not exist) |

Delete the private key from your machine after saving it in GitHub.

Permissions: the deploy workflow has `packages: write` only in the job that publishes the image;
the deploy job sends the server a `GITHUB_TOKEN` with `packages: read`. Actions are pinned by
commit sha; Dependabot updates them every week together with the dependencies and the base images.

**CodeQL** has no file in the repository: it is enabled with GitHub's "default setup" (Settings →
Code security → CodeQL analysis → Default), which analyzes Python and JavaScript/TypeScript on
every PR and push to `main`. If a `codeql.yml` were added ("advanced setup"), the default setup
would stop running.

## 4. What a deploy does

`deploy.yml` runs when the CI of a push to `main` finishes successfully (never for a PR):

1. If another commit reached `main` while CI was running, it does nothing (and says so in the
   job's summary): the CI of that new commit will deploy it.
2. It builds the image, pushes it with the `<sha>` and `latest` tags and takes its digest.
3. Over SSH it runs `deploy.sh "<sha> <digest>"` on the server, which:
   1. Validates sha, digest and token, ignores the SSH connection dropping, and takes a lock (one
      deploy at a time; on GitHub running deploys are not cancelled either).
   2. Logs in to GHCR with the token, pulls `ghcr.io/michelito-app/michelito@<digest>` and gives it
      the local tag `<sha>`.
   3. Backs up `feedback.db` (with SQLite's backup API, inside the container) to
      `/opt/michelito/backups/`, and keeps the last 10. If there is a database and it cannot be
      backed up, it does not deploy.
   4. Writes `MICHELITO_TAG` and `MICHELITO_DIGEST` to `.env`, runs `docker compose up -d`, and
      waits up to 90 s for `/api/health`.
   5. If it does not answer, it goes back to the version that was running (or, if the same one was
      redeployed, to the previous one), starts it and exits with an error: the job fails. It never
      goes back to a version from before the English rename (see "Upgrading from the Spanish
      layout").
   6. If it answers, it saves the one that was running in `previous-tag`, logs out of GHCR and
      removes old images (it keeps the current and the previous one).
4. It checks `https://demo.michelito.app/api/health` from outside. This check **only warns**: if it
   fails (DNS, certificate, Caddy), the job fails but the new version stays in place, because it
   already answered from inside. Check `docker compose logs caddy` and, if needed, roll back
   (section 6).

### The first deploy

The deploy workflow only exists for GitHub once it is on `main`, and it is triggered when a CI run
finishes. With the server and the secrets ready:

- if the repo already has a successful CI run on `main`, open in Actions the "Deploy demo" run
  that was skipped or failed and press *Re-run all jobs* (it uses the same commit; if it is no
  longer the tip of `main`, it will not deploy: use the other option);
- or push a new commit to `main` (even a documentation one): CI runs and, when it passes, it
  deploys.

## 5. Reading the feedback

```bash
sudo -u deploy docker compose --project-directory /opt/michelito exec -T app michelito feedback --data /data
sudo -u deploy docker compose --project-directory /opt/michelito exec -T app michelito feedback --data /data --usage
sudo -u deploy docker compose --project-directory /opt/michelito exec -T app michelito feedback --data /data --json > feedback.json
```

(`sudo -u deploy` because `.env` is readable only by `deploy`; `deploy`'s key gives no terminal,
but the admin can use that user with `sudo`.)

## 6. Rolling back

- From GitHub: Actions → "Deploy demo" → *Run workflow* (branch `main`, action `rollback`). It goes
  back to the previous version; another `rollback` goes back to the one before.
- On the server (without a token: the previous image is still there):
  ```bash
  sudo -u deploy env SSH_ORIGINAL_COMMAND=rollback /opt/michelito/deploy.sh </dev/null
  ```
- To a specific version: `git revert` on `main`; CI and the deploy do the rest.

## 7. Backups

- `/data` lives in the `michelito_datos` volume (template, visitors' copies and `feedback.db`). <!-- spanish-data -->
- `feedback.db` is backed up before each deploy to `/opt/michelito/backups/` (the last 10, readable
  only by `deploy`). One by hand, with the same SQLite API:
  ```bash
  sudo -u deploy docker compose --project-directory /opt/michelito exec -T app python -c \
    "import sqlite3; sqlite3.connect('file:/data/feedback.db?mode=ro', uri=True).backup(sqlite3.connect('/tmp/r.db'))"
  sudo -u deploy docker compose --project-directory /opt/michelito cp app:/tmp/r.db /opt/michelito/backups/feedback-manual.db
  ```
- Visitors' copies are not backed up: they delete themselves after 24 h and come from the
  template.
- Take a copy off the VPS from time to time (`scp` of the latest backup) or enable the provider's
  snapshots.

## 8. Updating the system

- Ubuntu: `unattended-upgrades` applies the security ones; from time to time
  `sudo apt update && sudo apt full-upgrade` and, if it asks, `sudo reboot` (the containers come
  back on their own).
- Docker and compose are updated with `apt` (Docker's repository).
- The app's image and Caddy's: through Dependabot's PRs. A change in `Caddyfile` or
  `docker-compose.yml` does **not** reach the server on its own: copy it to `/opt/michelito` (as in
  section 2, mode 644) and run
  `sudo -u deploy docker compose --project-directory /opt/michelito up -d` (or `… restart caddy` if
  only the Caddyfile changed).

## 9. Later: Cloudflare's proxy

If Cloudflare's orange cloud (proxy) is turned on:

1. Connections to Caddy will come from Cloudflare's IPs: without further changes, all visitors
   would share the per-IP copy quota. **Caddy** has to be told to trust Cloudflare and to take the
   client's IP from its header, in the Caddyfile's global options:
   ```
   servers {
       protocols h1 h2
       trusted_proxies static <ranges from cloudflare.com/ips-v4 and ips-v6>
       client_ip_headers CF-Connecting-IP
   }
   ```
   and, inside `reverse_proxy`, `header_up X-Forwarded-For {client_ip}` (without that line, Caddy
   keeps the `X-Forwarded-For` Cloudflare brings and appends Cloudflare's IP at the end, which is
   what the app would take). That way the app still receives a single hop with the real IP, and
   **`--trusted-proxy` / `MICHELITO_NET` do not change** (the app only trusts Caddy). What must not
   be done is putting Cloudflare's ranges in `MICHELITO_DEMO_PROXIES`: the app never talks to
   Cloudflare directly.
2. Cloudflare's SSL/TLS in **Full (strict)** (Caddy still has its certificate; with the proxy on,
   the HTTP-01 challenge works the same).
3. Optional: close 80/443 in the provider's firewall except for Cloudflare's ranges (ufw is not
   enough: Docker publishes the ports outside its rules).
4. Check that the CSP does not clash with what Cloudflare injects (Rocket Loader, analytics:
   better turned off).
