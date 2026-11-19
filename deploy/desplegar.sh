#!/usr/bin/env bash
# Despliega la demo en el servidor. Se instala en /opt/michelito/desplegar.sh y es el *forced
# command* de la llave de despliegue (ver docs/despliegue.md):
#
#   command="/opt/michelito/desplegar.sh",restrict ssh-ed25519 AAAA… despliegue-github
#
# Entrada (nada más se acepta):
#   SSH_ORIGINAL_COMMAND  «<sha> sha256:<digest>» (40 y 64 hex, un espacio) o «rollback»
#   stdin                 el token de GHCR (una línea; nunca por argumento ni entorno)
#
# Se despliega siempre por digest (`imagen@sha256:…`): lo que corre es exactamente lo que
# construyó el workflow. El sha solo nombra la versión (etiqueta local, nombre del respaldo).
#
# Pasos: entra a GHCR con el token (configuración de docker temporal), baja la imagen, respalda
# opiniones.db (conserva 10), escribe MICHELITO_TAG y MICHELITO_DIGEST en .env,
# `docker compose up -d` y espera /api/health. Si no responde, vuelve a la versión que estaba (o,
# si era la misma, a la anterior) y termina con error. Al final sale de GHCR y borra las imágenes
# viejas (conserva la actual y la anterior). «rollback» vuelve a la anterior (sin bajar nada si su
# imagen sigue en el servidor).
set -Eeuo pipefail
umask 077
trap '' HUP # si se corta el SSH, el despliegue termina igual (y su vuelta atrás, si hace falta)

DIR=${MICHELITO_DIR:-/opt/michelito}
ESPERA=${MICHELITO_ESPERA:-90}    # segundos que se espera /api/health
INTERVALO=${MICHELITO_INTERVALO:-3}
RESPALDOS_A_CONSERVAR=10
SHA_RE='[0-9a-f]{40}'
DIGEST_RE='sha256:[0-9a-f]{64}'
VERSION_RE="^($SHA_RE) ($DIGEST_RE)\$"

log() { printf '[desplegar] %s\n' "$*"; }
die() {
	printf '[desplegar] error: %s\n' "$*" >&2
	exit "${2:-1}"
}

[[ $ESPERA =~ ^[0-9]+$ && $INTERVALO =~ ^[0-9]+$ ]] || die "MICHELITO_ESPERA/INTERVALO no son números" 2
cd "$DIR" || die "no existe $DIR" 2
[[ -f .env ]] || die "falta $DIR/.env" 2

# Lee una variable de .env sin ejecutarlo.
env_get() {
	local line
	line=$(grep -E "^$1=" .env | tail -n 1 || true)
	line=${line#*=}
	line=${line%\"}
	line=${line#\"}
	printf '%s' "$line"
}

# Escribe la versión (sha y digest) en .env: en un temporal que se revisa antes del mv, así .env
# nunca queda a medias ni sin MICHELITO_IMAGE.
set_version() {
	local tmp estado=0
	tmp=$(mktemp .env.XXXXXX) || return 1
	grep -vE '^MICHELITO_(TAG|DIGEST)=' .env >"$tmp" || estado=$?
	if ((estado > 1)) ||
		! printf 'MICHELITO_TAG=%s\nMICHELITO_DIGEST=%s\n' "$1" "$2" >>"$tmp" ||
		! grep -qE '^MICHELITO_IMAGE=' "$tmp" ||
		! chmod 600 "$tmp"; then
		rm -f "$tmp"
		log "no se pudo escribir .env"
		return 1
	fi
	mv -f "$tmp" .env
}

# --- Entrada -----------------------------------------------------------------------------------
pedido=${SSH_ORIGINAL_COMMAND:-}
if [[ $pedido == rollback ]]; then
	accion=rollback
elif [[ $pedido =~ $VERSION_RE ]]; then
	accion=desplegar
	destino_sha=${BASH_REMATCH[1]}
	destino_digest=${BASH_REMATCH[2]}
else
	die "pedido no válido: se espera «<sha de 40 hex> sha256:<64 hex>» o «rollback»" 2
fi

IMAGEN=$(env_get MICHELITO_IMAGE)
GHCR_USER=$(env_get GHCR_USER)
[[ $IMAGEN =~ ^ghcr\.io/[a-z0-9][a-z0-9._/-]*$ ]] || die "MICHELITO_IMAGE en .env no es una imagen de ghcr.io" 2
[[ $GHCR_USER =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || die "GHCR_USER en .env no es un usuario de GitHub" 2

token=""
if [[ ! -t 0 ]]; then
	IFS= read -r -t 10 token || true
fi
token=${token%$'\r'}
if [[ -n $token && ! $token =~ ^[A-Za-z0-9_]{20,255}$ ]]; then
	die "el token de stdin no tiene forma de token de GitHub" 2
fi
if [[ $accion == desplegar && -z $token ]]; then
	die "falta el token de GHCR por stdin" 2
fi

# Un despliegue a la vez.
exec 9>"$DIR/.desplegar.lock"
flock -w 120 9 || die "otro despliegue sigue en curso"

# Credenciales de docker solo durante este despliegue.
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG
logueado=0
limpiar() {
	if ((logueado)); then
		docker logout ghcr.io >/dev/null 2>&1 || true
	fi
	rm -rf "$DOCKER_CONFIG"
}
trap limpiar EXIT

entrar() {
	if ((!logueado)); then
		printf '%s\n' "$token" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null ||
			return 1
		logueado=1
	fi
}

# La versión en uso (.env) y la anterior (etiqueta-anterior: «<sha> <digest>»).
anterior_archivo="$DIR/etiqueta-anterior"
actual_sha=$(env_get MICHELITO_TAG)
actual_digest=$(env_get MICHELITO_DIGEST)
actual=""
if [[ -n $actual_sha || -n $actual_digest ]]; then
	actual="$actual_sha $actual_digest"
	[[ $actual =~ $VERSION_RE ]] || die "MICHELITO_TAG/MICHELITO_DIGEST en .env no son válidos" 2
fi
anterior=""
[[ -f $anterior_archivo ]] && anterior=$(<"$anterior_archivo")
[[ -z $anterior || $anterior =~ $VERSION_RE ]] || die "etiqueta-anterior no es válida" 2

if [[ $accion == rollback ]]; then
	[[ -n $anterior ]] || die "no hay versión anterior a la que volver"
	destino_sha=${anterior% *}
	destino_digest=${anterior#* }
fi
log "acción: $accion · actual: ${actual_sha:-ninguna} · destino: $destino_sha ($destino_digest)"

# --- Imagen ------------------------------------------------------------------------------------
# Se baja por digest y se le pone la etiqueta local <sha>: así `image prune` no la toma por
# huérfana y se sabe qué imágenes conservar. (Se llama dentro de `||`, donde `set -e` no actúa:
# cada paso devuelve su error a mano.)
traer() { # sha digest
	if ! docker image inspect "$IMAGEN@$2" >/dev/null 2>&1; then
		[[ -n $token ]] || {
			log "la imagen $1 no está en el servidor y no llegó token para bajarla"
			return 1
		}
		entrar || return 1
		log "bajando $IMAGEN@$2"
		MICHELITO_TAG=$1 MICHELITO_DIGEST=$2 docker compose pull --quiet app || return 1
	fi
	docker image tag "$IMAGEN@$2" "$IMAGEN:$1" || return 1
}

traer "$destino_sha" "$destino_digest" || die "no se pudo obtener la imagen $destino_sha"

# --- Respaldo de opiniones.db ------------------------------------------------------------------
# Con la API de respaldo de SQLite (lo mismo que `sqlite3 .backup`) dentro del contenedor, a su
# /tmp, y de ahí a stdout. Sale con 3 si no hay base todavía.
RESPALDO_PY='
import os, sqlite3, sys, tempfile
origen = "/datos/opiniones.db"
if not os.path.exists(origen):
    sys.exit(3)
with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".db") as tmp:
    src = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp.name)
    src.backup(dst)
    dst.close()
    src.close()
    with open(tmp.name, "rb") as f:
        sys.stdout.buffer.write(f.read())
'

respaldar() {
	if [[ -z $actual ]] || [[ -z $(docker compose ps --quiet --status running app 2>/dev/null) ]]; then
		log "sin contenedor en marcha: no hay opiniones que respaldar"
		return 0
	fi
	mkdir -p respaldos
	local destino_respaldo tmp estado=0
	destino_respaldo="respaldos/opiniones-$(date -u +%Y%m%dT%H%M%SZ)-${actual_sha:0:12}.db"
	tmp=$(mktemp respaldos/.parcial.XXXXXX)
	docker compose exec -T app python -c "$RESPALDO_PY" >"$tmp" || estado=$?
	if ((estado == 3)); then
		rm -f "$tmp"
		log "todavía no hay opiniones.db: nada que respaldar"
		return 0
	fi
	if ((estado != 0)) || [[ $(head -c 15 "$tmp") != "SQLite format 3" ]]; then
		rm -f "$tmp"
		die "no se pudo respaldar opiniones.db: no se despliega"
	fi
	mv -f "$tmp" "$destino_respaldo"
	log "respaldo: $destino_respaldo"
	find respaldos -maxdepth 1 -name 'opiniones-*.db' -type f | sort -r |
		tail -n "+$((RESPALDOS_A_CONSERVAR + 1))" | while IFS= read -r viejo; do
		rm -f -- "$viejo"
	done
}

# --- Salud -------------------------------------------------------------------------------------
SALUD_PY='
import os, urllib.request
urllib.request.urlopen("http://127.0.0.1:" + os.environ["FINANZAS_DEMO_PUERTO"] + "/api/health", timeout=4)
'

esperar_salud() {
	local limite=$((SECONDS + ESPERA))
	while ((SECONDS < limite)); do
		if docker compose exec -T app python -c "$SALUD_PY" >/dev/null 2>&1; then
			return 0
		fi
		sleep "$INTERVALO"
	done
	return 1
}

poner() { # sha digest (dentro de `if`/`&&`: sin `set -e`, los errores se devuelven a mano)
	set_version "$1" "$2" || return 1
	docker compose up -d --remove-orphans || return 1
}

respaldar
log "levantando $destino_sha"
if poner "$destino_sha" "$destino_digest" && esperar_salud; then
	log "en marcha: $destino_sha responde /api/health"
else
	# A qué volver: la que estaba si era otra imagen; si no (se redesplegó la misma), la anterior.
	respaldo=""
	if [[ -n $actual && ${actual#* } != "$destino_digest" ]]; then
		respaldo=$actual
	elif [[ -n $anterior && ${anterior#* } != "$destino_digest" ]]; then
		respaldo=$anterior
	fi
	if [[ -n $respaldo ]]; then
		log "$destino_sha no respondió en ${ESPERA}s: vuelvo a ${respaldo% *}"
		if traer "${respaldo% *}" "${respaldo#* }" && poner "${respaldo% *}" "${respaldo#* }" &&
			esperar_salud; then
			log "de vuelta en ${respaldo% *}"
		else
			log "¡${respaldo% *} tampoco responde! Revisar a mano: docker compose logs app"
		fi
	else
		log "$destino_sha no respondió en ${ESPERA}s y no hay otra versión a la que volver"
	fi
	exit 1
fi

# La anterior pasa a ser la que estaba (en «rollback», así se puede volver otra vez).
if [[ -n $actual && ${actual#* } != "$destino_digest" ]]; then
	printf '%s\n' "$actual" >"$anterior_archivo"
fi

# --- Limpieza ----------------------------------------------------------------------------------
if ((logueado)); then
	docker logout ghcr.io >/dev/null 2>&1 || true
	logueado=0
fi
conservar=$(cat "$anterior_archivo" 2>/dev/null || true)
conservar=${conservar% *}
docker image ls "$IMAGEN" --format '{{.Tag}}' | while IFS= read -r etiqueta; do
	case $etiqueta in
	"$destino_sha" | "$conservar" | "" | "<none>") ;;
	*) docker image rm "$IMAGEN:$etiqueta" >/dev/null 2>&1 || true ;;
	esac
done
docker image prune -f >/dev/null 2>&1 || true
log "listo"
