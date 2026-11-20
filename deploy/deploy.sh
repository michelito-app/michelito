#!/usr/bin/env bash
# Deploys the demo and the hosted app on the server. Installed as /opt/michelito/deploy.sh, it
# is the *forced command* of the deploy key (see docs/deployment.md):
#
#   command="/opt/michelito/deploy.sh",restrict ssh-ed25519 AAAA… github-deploy
#
# Input (nothing else is accepted):
#   SSH_ORIGINAL_COMMAND  "<sha> sha256:<digest>" (40 and 64 hex, one space) or "rollback"
#   stdin                 the GHCR token (one line; never as an argument or in the environment)
#
# It always deploys by digest (`image@sha256:…`): what runs is exactly what the workflow built.
# The sha only names the version (local tag, backup name).
#
# Steps: log in to GHCR with the token (temporary docker config), pull the image, back up
# feedback.db (keeps 10) and, with the "hosted" profile, the hosted app's folder (encrypted, in
# its volume, keeps 10), write MICHELITO_TAG and MICHELITO_DIGEST to .env,
# `docker compose up -d` and wait for /api/health (of both, with the "hosted" profile). If it does not answer, go back to the version
# that was running (or, if it was the same one, to the previous one) and exit with an error.
# Finally log out of GHCR and remove old images (keeps the current and the previous one).
# "rollback" goes back to the previous version (without pulling if its image is still here).
set -Eeuo pipefail
umask 077
trap '' HUP # if the SSH connection drops, the deploy still finishes (and its rollback, if needed)

DIR=${MICHELITO_DIR:-/opt/michelito}
WAIT=${MICHELITO_WAIT:-90} # seconds to wait for /api/health
INTERVAL=${MICHELITO_INTERVAL:-3}
BACKUPS_TO_KEEP=10
SHA_RE='[0-9a-f]{40}'
DIGEST_RE='sha256:[0-9a-f]{64}'
VERSION_RE="^($SHA_RE) ($DIGEST_RE)\$"

log() { printf '[deploy] %s\n' "$*"; }
die() {
	printf '[deploy] error: %s\n' "$*" >&2
	exit "${2:-1}"
}

[[ $WAIT =~ ^[0-9]+$ && $INTERVAL =~ ^[0-9]+$ ]] || die "MICHELITO_WAIT/INTERVAL are not numbers" 2
cd "$DIR" || die "$DIR does not exist" 2
[[ -f .env ]] || die "$DIR/.env is missing" 2

# Whether .env turns on the hosted app (COMPOSE_PROFILES=...hosted...).
hosted_enabled() {
	[[ ,$(env_get COMPOSE_PROFILES), == *,hosted,* ]]
}

# Reads a variable from .env without executing it.
env_get() {
	local line
	line=$(grep -E "^$1=" .env | tail -n 1 || true)
	line=${line#*=}
	line=${line%\"}
	line=${line#\"}
	printf '%s' "$line"
}

# Writes the version (sha and digest) to .env: into a temporary file that is checked before the
# mv, so .env is never left half-written or without MICHELITO_IMAGE.
set_version() {
	local tmp status=0
	tmp=$(mktemp .env.XXXXXX) || return 1
	grep -vE '^MICHELITO_(TAG|DIGEST)=' .env >"$tmp" || status=$?
	if ((status > 1)) ||
		! printf 'MICHELITO_TAG=%s\nMICHELITO_DIGEST=%s\n' "$1" "$2" >>"$tmp" ||
		! grep -qE '^MICHELITO_IMAGE=' "$tmp" ||
		! chmod 600 "$tmp"; then
		rm -f "$tmp"
		log "could not write .env"
		return 1
	fi
	mv -f "$tmp" .env
}

# --- Input -------------------------------------------------------------------------------------
request=${SSH_ORIGINAL_COMMAND:-}
if [[ $request == rollback ]]; then
	action=rollback
elif [[ $request =~ $VERSION_RE ]]; then
	action=deploy
	target_sha=${BASH_REMATCH[1]}
	target_digest=${BASH_REMATCH[2]}
else
	die "invalid request: expected \"<40-hex sha> sha256:<64 hex>\" or \"rollback\"" 2
fi

IMAGE=$(env_get MICHELITO_IMAGE)
GHCR_USER=$(env_get GHCR_USER)
[[ $IMAGE =~ ^ghcr\.io/[a-z0-9][a-z0-9._/-]*$ ]] || die "MICHELITO_IMAGE in .env is not a ghcr.io image" 2
[[ $GHCR_USER =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || die "GHCR_USER in .env is not a GitHub user" 2

token=""
if [[ ! -t 0 ]]; then
	IFS= read -r -t 10 token || true
fi
token=${token%$'\r'}
if [[ -n $token && ! $token =~ ^[A-Za-z0-9._~+/=-]{20,4096}$ ]]; then
	die "the token on stdin does not look like a GitHub token" 2
fi
if [[ $action == deploy && -z $token ]]; then
	die "the GHCR token is missing on stdin" 2
fi

# One deploy at a time.
exec 9>"$DIR/.deploy.lock"
flock -w 120 9 || die "another deploy is still running"

# Docker credentials only for the duration of this deploy.
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG
logged_in=0
cleanup() {
	if ((logged_in)); then
		docker logout ghcr.io >/dev/null 2>&1 || true
	fi
	rm -rf "$DOCKER_CONFIG"
}
trap cleanup EXIT

login() {
	if ((!logged_in)); then
		printf '%s\n' "$token" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null ||
			return 1
		logged_in=1
	fi
}

# The running version (.env) and the previous one (previous-tag: "<sha> <digest>").
previous_file="$DIR/previous-tag"
# Versions recorded before this script existed come from the release before the English rename:
# those images read other environment variables and another data path, so with this compose
# file they would start (and pass the health check) writing to a throwaway volume. The marker
# says the versions in .env and previous-tag were recorded by this script; until the first
# successful deploy writes it, the running version is not a target for "rollback" or for
# falling back, and the legacy previous-version file is ignored.
state_marker="$DIR/.deploy-state-v2"
current_sha=$(env_get MICHELITO_TAG)
current_digest=$(env_get MICHELITO_DIGEST)
current=""
if [[ -n $current_sha || -n $current_digest ]]; then
	current="$current_sha $current_digest"
	[[ $current =~ $VERSION_RE ]] || die "MICHELITO_TAG/MICHELITO_DIGEST in .env are not valid" 2
fi
pre_rename=0
if [[ ! -f $state_marker ]]; then
	if [[ -n $current ]]; then
		pre_rename=1
	else
		touch "$state_marker" # a new server: every version it records comes from this script
	fi
fi
previous=""
if [[ -f $state_marker && -f $previous_file ]]; then
	previous=$(<"$previous_file")
fi
[[ -z $previous || $previous =~ $VERSION_RE ]] || die "the previous version file is not valid" 2

if [[ $action == rollback ]] && ((pre_rename)); then
	die "the running version predates the English rename: there is no version to roll back to with this script (see docs/deployment.md, \"Upgrading from the Spanish layout\")"
fi
if [[ $action == rollback ]]; then
	[[ -n $previous ]] || die "there is no previous version to go back to"
	target_sha=${previous% *}
	target_digest=${previous#* }
fi
log "action: $action · current: ${current_sha:-none} · target: $target_sha ($target_digest)"

# --- Image -------------------------------------------------------------------------------------
# Pulled by digest and given the local tag <sha>: that way `image prune` does not take it for
# dangling and we know which images to keep. (Called inside `||`, where `set -e` does not act:
# each step returns its error by hand.)
fetch() { # sha digest
	if ! docker image inspect "$IMAGE@$2" >/dev/null 2>&1; then
		[[ -n $token ]] || {
			log "image $1 is not on the server and no token arrived to pull it"
			return 1
		}
		login || return 1
		log "pulling $IMAGE@$2"
		MICHELITO_TAG=$1 MICHELITO_DIGEST=$2 docker compose pull --quiet app || return 1
	fi
	docker image tag "$IMAGE@$2" "$IMAGE:$1" || return 1
}

fetch "$target_sha" "$target_digest" || die "could not get image $target_sha"

# --- Backup of feedback.db ---------------------------------------------------------------------
# With SQLite's backup API (same as `sqlite3 .backup`) inside the container, to its /tmp, and
# from there to stdout. Exits with 3 if there is no database yet.
BACKUP_PY='
import os, sqlite3, sys, tempfile
source = "/data/feedback.db"
if not os.path.exists(source):
    sys.exit(3)
with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".db") as tmp:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp.name)
    src.backup(dst)
    dst.close()
    src.close()
    with open(tmp.name, "rb") as f:
        sys.stdout.buffer.write(f.read())
'

back_up() {
	if [[ -z $current ]] || [[ -z $(docker compose ps --quiet --status running app 2>/dev/null) ]]; then
		log "no running container: no feedback to back up"
		return 0
	fi
	mkdir -p backups
	local backup_file tmp status=0
	backup_file="backups/feedback-$(date -u +%Y%m%dT%H%M%SZ)-${current_sha:0:12}.db"
	tmp=$(mktemp backups/.partial.XXXXXX)
	docker compose exec -T app python -c "$BACKUP_PY" >"$tmp" || status=$?
	if ((status == 3)); then
		rm -f "$tmp"
		log "there is no feedback.db yet: nothing to back up"
		return 0
	fi
	if ((status != 0)) || [[ $(head -c 15 "$tmp") != "SQLite format 3" ]]; then
		rm -f "$tmp"
		die "could not back up feedback.db: not deploying"
	fi
	mv -f "$tmp" "$backup_file"
	log "backup: $backup_file"
	find backups -maxdepth 1 -name 'feedback-*.db' -type f | sort -r |
		tail -n "+$((BACKUPS_TO_KEEP + 1))" | while IFS= read -r old; do
		rm -f -- "$old"
	done
}

# --- Backup of the hosted app -------------------------------------------------------------------
# `michelito backup --to` in the `backup` service (whether or not the hosted app is running): a
# consistent snapshot of every account's encrypted database and of the sealed accounts database,
# in the hosted volume (/data/deploy-backups, keeps 10). Nothing leaves the server; the master key
# is not in it. With the profile on, the hosted app is never deployed without it: an empty volume
# (the hosted app never ran) is the only case with nothing to back up.
back_up_hosted() {
	hosted_enabled || return 0
	if [[ -z $current ]]; then
		log "first deploy: there is no hosted data to back up yet"
		return 0
	fi
	if ! docker compose run --rm -T backup backup --to /data/deploy-backups \
		--keep "$BACKUPS_TO_KEEP" --label "${current_sha:0:12}" --skip-empty; then
		die "could not back up the hosted app: not deploying"
	fi
	log "backup of the hosted app: /data/deploy-backups (in its volume)"
}

# --- Health ------------------------------------------------------------------------------------
# The port defaults to 8600 for an image that does not set MICHELITO_DEMO_PORT.
HEALTH_PY='
import os, urllib.request
urllib.request.urlopen("http://127.0.0.1:" + os.environ.get("MICHELITO_DEMO_PORT", "8600") + "/api/health", timeout=4)
'

HOSTED_HEALTH_PY='
import os, urllib.request
urllib.request.urlopen("http://127.0.0.1:" + os.environ.get("MICHELITO_HOSTED_PORT", "8620") + "/api/health", timeout=4)
'

healthy() {
	docker compose exec -T app python -c "$HEALTH_PY" >/dev/null 2>&1 || return 1
	if hosted_enabled; then
		docker compose exec -T hosted python -c "$HOSTED_HEALTH_PY" >/dev/null 2>&1 || return 1
	fi
}

wait_for_health() {
	local deadline=$((SECONDS + WAIT))
	while ((SECONDS < deadline)); do
		if healthy; then
			return 0
		fi
		sleep "$INTERVAL"
	done
	return 1
}

start() { # sha digest (inside `if`/`&&`: without `set -e`, errors are returned by hand)
	set_version "$1" "$2" || return 1
	docker compose up -d --remove-orphans || return 1
}

back_up
back_up_hosted
log "starting $target_sha"
if start "$target_sha" "$target_digest" && wait_for_health; then
	log "running: $target_sha answers /api/health"
else
	# What to go back to: the one that was running if it was another image; otherwise (the same
	# one was redeployed), the previous one.
	fallback=""
	if ((pre_rename)); then
		log "the running version predates the English rename: not going back to it"
	elif [[ -n $current && ${current#* } != "$target_digest" ]]; then
		fallback=$current
	elif [[ -n $previous && ${previous#* } != "$target_digest" ]]; then
		fallback=$previous
	fi
	if [[ -n $fallback ]]; then
		log "$target_sha did not answer within ${WAIT}s: going back to ${fallback% *}"
		if fetch "${fallback% *}" "${fallback#* }" && start "${fallback% *}" "${fallback#* }" &&
			wait_for_health; then
			log "back on ${fallback% *}"
		else
			log "${fallback% *} does not answer either! Check by hand: docker compose logs app hosted"
		fi
	else
		log "$target_sha did not answer within ${WAIT}s and there is no other version to go back to"
	fi
	exit 1
fi

# The previous version becomes the one that was running (on "rollback", so it can go back again),
# unless it predates the English rename.
if ((pre_rename)); then
	rm -f "$previous_file"
elif [[ -n $current && ${current#* } != "$target_digest" ]]; then
	printf '%s\n' "$current" >"$previous_file"
fi
touch "$state_marker"

# --- Cleanup -----------------------------------------------------------------------------------
if ((logged_in)); then
	docker logout ghcr.io >/dev/null 2>&1 || true
	logged_in=0
fi
# Keeps the previous image (or, right after the upgrade, the pre-rename one for a manual rollback).
keep=""
if ((pre_rename)); then
	keep=$current
elif [[ -f $previous_file ]]; then
	keep=$(<"$previous_file")
fi
keep=${keep% *}
docker image ls "$IMAGE" --format '{{.Tag}}' | while IFS= read -r tag; do
	case $tag in
	"$target_sha" | "$keep" | "" | "<none>") ;;
	*) docker image rm "$IMAGE:$tag" >/dev/null 2>&1 || true ;;
	esac
done
docker image prune -f >/dev/null 2>&1 || true
log "done"
