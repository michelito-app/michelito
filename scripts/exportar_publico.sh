#!/usr/bin/env bash
# Crea en DESTINO (un directorio nuevo) un repositorio git con un único commit del HEAD actual,
# sin el historial de este. No crea remotos ni hace push: eso lo haces tú después.
#
#   GIT_AUTHOR_NAME="Tu nombre público" \
#   GIT_AUTHOR_EMAIL="<id>+<usuario>@users.noreply.github.com" \
#   scripts/exportar_publico.sh DESTINO
#
# La identidad del commit es obligatoria y explícita: nunca se toma la de tu configuración de
# git (que puede tener tu nombre real o un correo del trabajo). El committer es el mismo autor.
#
# Solo entra lo versionado en HEAD (`git archive`): los cambios sin commit y lo ignorado
# (.superpowers/, bases, PDFs…) quedan fuera. Antes del commit corre scripts/check_private.py
# sobre la copia y se detiene si encuentra algo.
set -euo pipefail

readonly MESSAGE="feat: versión inicial pública"

if [[ $# -ne 1 || -z "$1" ]]; then
  echo "Uso: $0 DESTINO   (DESTINO no debe existir)" >&2
  exit 2
fi
destination="$1"
if [[ -e "$destination" ]]; then
  echo "Error: $destination ya existe; elige un directorio nuevo." >&2
  exit 2
fi
if [[ -z "${GIT_AUTHOR_NAME:-}" || -z "${GIT_AUTHOR_EMAIL:-}" ]]; then
  echo "Error: define GIT_AUTHOR_NAME y GIT_AUTHOR_EMAIL con la identidad pública del commit;" >&2
  echo "por ejemplo el correo privado de GitHub: <id>+<usuario>@users.noreply.github.com" >&2
  echo "(GitHub → Settings → Emails). No se usa la identidad de tu configuración de git." >&2
  exit 2
fi
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

source_root="$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)"
target="$(realpath -m -- "$destination")"
if [[ "$target" == "$source_root" || "$target" == "$source_root"/* ]]; then
  echo "Error: DESTINO no puede estar dentro del repositorio de origen ($source_root)." >&2
  exit 2
fi
if [[ -n "$(git -C "$source_root" status --porcelain --untracked-files=no)" ]]; then
  echo "Aviso: hay cambios sin commit; se exporta HEAD sin ellos." >&2
fi
revision="$(git -C "$source_root" rev-parse --short HEAD)"

mkdir -p -- "$destination"
git -C "$source_root" archive --format=tar HEAD | tar -x -C "$destination"

# Sin firmas ni hooks de la configuración global: el commit solo lleva la identidad de arriba.
local_git=(git -C "$destination" -c commit.gpgsign=false -c core.hooksPath=/dev/null)
"${local_git[@]}" init -q -b main
"${local_git[@]}" add -A
if ! python3 "$destination/scripts/check_private.py" "$destination"; then
  echo "Error: la copia tiene posibles datos personales; no se hizo el commit." >&2
  echo "Corrígelo en el repositorio de origen y borra $destination antes de reintentar." >&2
  exit 1
fi
"${local_git[@]}" commit -q -m "$MESSAGE"

echo "Listo: $destination tiene un único commit con el árbol de $revision,"
echo "con autor $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>."
echo "Para publicarlo: crea el repositorio en GitHub, luego"
echo "  git -C \"$destination\" remote add origin <url> && git -C \"$destination\" push -u origin main"
