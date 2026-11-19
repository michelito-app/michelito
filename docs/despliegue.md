# Despliegue de la demo (Michelito)

La demo pública corre en un VPS con Docker: la imagen de la app (`finanzas demo`, datos
inventados) detrás de Caddy, que pone HTTPS y las cabeceras de seguridad. GitHub Actions la
construye y la despliega sola cada vez que el CI pasa en `main`; si la versión nueva no responde,
el servidor vuelve a la anterior y el job falla.

En este documento `demo.michelito.app` es el host por omisión, `michelito-app/michelito` el repo y
`ghcr.io/michelito-app/michelito` la imagen; cámbialos si usas otros. Los comandos del servidor
están escritos para tu usuario administrador (con `sudo`) y rutas absolutas.

## Arquitectura

```
visitante ──https (IPv4/IPv6)──▶ Caddy (80/443, Let's Encrypt) ──http──▶ app (finanzas demo, :8600)
                                 redes «publica» + «interna»            solo «interna», sin internet
                                                                         volumen «datos» → /datos
GitHub Actions
  CI (ci.yml): pytest, ruff, mypy, check_private · lint, typecheck, vitest, build · Playwright
  └─ si pasa en main y el commit sigue siendo la punta de main → deploy.yml
       imagen    → ghcr.io/michelito-app/michelito:<sha> y :latest (y su digest)
       desplegar (environment «demo») → ssh deploy@VPS "<sha> <digest>"  (token por stdin)
                                       → curl https://demo.michelito.app/api/health
```

- **Imagen** (`Dockerfile`): compila la interfaz con Node, instala la app con `uv sync --frozen
  --no-dev` y deja en la final solo Python y el entorno, sin pip, uv, Node ni el código fuente.
  Corre como el usuario `michelito` (uid 10001), solo con `finanzas demo` (`FINANZAS_MODO=demo`:
  nada de Gmail, keyring ni datos reales). Plantilla, copias y `opiniones.db` van en `/datos`.
  Su `HEALTHCHECK` pide `/api/health`.
- **Compose** (`deploy/docker-compose.yml`): la app corre por digest (`imagen@sha256:…`, lo que
  construyó el workflow), sin puertos publicados, en la red `interna` (sin salida a internet).
  Los dos contenedores tienen el sistema de archivos de solo lectura (salvo sus volúmenes y un
  `/tmp` en memoria), sin capacidades (Caddy solo la de abrir 80/443), `no-new-privileges`,
  límite de procesos y de memoria (app 512 MB, Caddy 128 MB), y se reinician solos.
  La red `publica` tiene IPv6 propio (ver «IPv6»).
- **Caddy** (`deploy/Caddyfile`): certificado automático para `$MICHELITO_HOST`, compresión,
  HSTS, CSP estricta (todo del mismo origen, nada en línea), `X-Content-Type-Options`,
  `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`; quita `Server` y `Via`. Pone en
  `X-Forwarded-For` la IP de quien se conectó (un solo salto) y descarta el que mande el
  cliente; la app solo lo cree si viene de la red interna (`FINANZAS_DEMO_PROXIES`), y con él
  cuenta el cupo de copias por IP (solo en memoria).
- **Despliegue** (`deploy/desplegar.sh`): es el *forced command* de la llave de despliegue: esa
  llave no abre una terminal ni puede correr otra cosa. Acepta solo `«<sha> sha256:<digest>»`
  (40 y 64 caracteres hexadecimales) o `rollback`, y el token de GHCR por stdin. Ver «Qué hace un
  despliegue».

## 1. El servidor (una sola vez)

Un VPS con Ubuntu LTS (1 GB de RAM alcanza). Como root o con `sudo`:

1. Usuario administrador sin root con tu llave, y SSH solo con llave:
   ```bash
   adduser --disabled-password --gecos "" admin
   usermod -aG sudo admin
   # y copia tu llave pública al authorized_keys de admin (ssh-copy-id desde tu máquina)
   # /etc/ssh/sshd_config.d/10-endurecer.conf
   #   PasswordAuthentication no
   #   KbdInteractiveAuthentication no
   #   PermitRootLogin no
   systemctl reload ssh
   ```
   (Prueba entrar con la llave en otra terminal antes de cerrar la sesión de root.)
2. Firewall: `ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable`.
   Ojo: los puertos que publica Docker no pasan por las reglas de entrada de ufw; aquí solo se
   publican 80 y 443, que de todos modos están abiertos.
3. Actualizaciones automáticas de seguridad: `apt install unattended-upgrades` y
   `dpkg-reconfigure -plow unattended-upgrades`.
4. Docker Engine con el plugin de compose, del repositorio oficial de Docker
   (docs.docker.com/engine/install/ubuntu). Para IPv6, ver la sección siguiente.
5. DNS: registros `A` y `AAAA` de `demo` hacia el VPS, en Cloudflare en modo **«DNS only»** (nube
   gris). Caddy necesita que el puerto 80 o 443 llegue directo para sacar el certificado.

### IPv6

Con un registro `AAAA`, parte de los visitantes llega por IPv6. Si la red de Caddy fuera solo
IPv4, Docker pasaría esas conexiones por `docker-proxy` y Caddy vería la puerta de enlace del
bridge (una IPv4 privada) en lugar del visitante: todos los de IPv6 compartirían un solo cupo de
copias. Por eso la red `publica` del compose tiene `enable_ipv6: true` y una subred ULA fija
(`MICHELITO_RED6`, por omisión `fd4d:6963:6865:6c00::/64`): así Docker publica 443 en IPv6 con
reglas `ip6tables` (DNAT), que conservan la IP de origen.

Del lado del daemon no hace falta nada en Docker 27 o más nuevo: `ip6tables` viene activado por
omisión (documentación de Docker, «Use IPv6 networking»). Solo revisa que nadie lo haya apagado:

```bash
sudo cat /etc/docker/daemon.json 2>/dev/null   # no debe decir "ip6tables": false
```

Opcional: `"userland-proxy": false` en `/etc/docker/daemon.json` (y `sudo systemctl restart
docker`) quita `docker-proxy` del todo; si algo quedara mal configurado, las conexiones IPv6
fallarían en vez de llegar con la IP equivocada. No es necesario con la red IPv6 del compose.

Verificación, después del primer despliegue:

```bash
# Desde una máquina con IPv6 (fuera del VPS):
curl -6 -fsS https://demo.michelito.app/api/health

# En el VPS: el 443 de IPv6 va al IPv6 del contenedor de Caddy (no a una IPv4 172.x):
pgrep -a docker-proxy | grep -- '-host-port 443'   # la línea de «::» debe decir -container-ip fd4d:…
```

La app no registra IPs (a propósito: ni siquiera en el registro). Para comprobar qué IP le llega
a Caddy (y por tanto a la app, que toma ese único salto), mira las conexiones abiertas dentro del
contenedor de Caddy mientras sostienes una desde afuera:

```bash
# Afuera, deja una conexión abierta unos segundos:
openssl s_client -connect demo.michelito.app:443 -6 -quiet </dev/null & sleep 10; kill %1
# En el VPS, a la vez:
sudo nsenter -t "$(sudo docker inspect -f '{{.State.Pid}}' michelito-caddy-1)" -n ss -tn 'sport = :443'
```

La columna «Peer Address» debe mostrar tu IPv6 pública, no `fd4d:…::1` ni `172.x.x.1` (la
puerta de enlace del bridge). Probado en local (Docker 27): con la red IPv6 Caddy ve la IPv6
real y los visitantes IPv4 e IPv6 tienen cupos separados; sin ella, las conexiones IPv6 llegan
como la puerta de enlace IPv4.

### Usuario y llave de despliegue

```bash
# En el servidor: el usuario que usa GitHub Actions (puede usar docker, nada más).
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
```

Ojo: estar en el grupo `docker` equivale a root en la máquina. Por eso la llave de ese usuario
solo puede correr `desplegar.sh` (forced command + `restrict`); no le des otra llave.

```bash
# En tu máquina: una llave solo para esto, sin frase (la guarda GitHub como secreto).
ssh-keygen -t ed25519 -N "" -C despliegue-github -f ./michelito-despliegue
```

## 2. Primer arranque en el servidor

Copia `deploy/docker-compose.yml`, `deploy/Caddyfile` y `deploy/desplegar.sh` del repositorio
(por ejemplo con `scp` a tu usuario admin) y, en el servidor, desde la carpeta donde quedaron:

```bash
sudo install -d -o deploy -g deploy -m 750 /opt/michelito
sudo install -o deploy -g deploy -m 640 docker-compose.yml Caddyfile /opt/michelito/
sudo install -o deploy -g deploy -m 750 desplegar.sh /opt/michelito/
sudo -u deploy tee /opt/michelito/.env >/dev/null <<'EOF'
MICHELITO_HOST=demo.michelito.app
MICHELITO_IMAGE=ghcr.io/michelito-app/michelito
GHCR_USER=michelito-app
EOF
sudo chmod 600 /opt/michelito/.env

# La llave de despliegue, atada a desplegar.sh:
DEPLOY_HOME=$(getent passwd deploy | cut -d: -f6)
sudo install -d -o deploy -g deploy -m 700 "$DEPLOY_HOME/.ssh"
echo 'command="/opt/michelito/desplegar.sh",restrict ssh-ed25519 AAAA…(contenido de michelito-despliegue.pub)… despliegue-github' \
  | sudo -u deploy tee "$DEPLOY_HOME/.ssh/authorized_keys" >/dev/null
sudo chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
```

- `MICHELITO_TAG` y `MICHELITO_DIGEST` (la versión en uso) **no** se escriben a mano: los agrega
  `desplegar.sh` en `.env`. Mientras no haya un primer despliegue, `docker compose` se niega a
  arrancar.
- `GHCR_USER`: cualquier nombre de GitHub sirve con el token del workflow; usa el de la
  organización.
- Opcionales en `.env`: `MICHELITO_RED` (la subred interna, `172.30.53.0/24`), `MICHELITO_RED6`
  (la IPv6 de la red pública; cámbialas si chocan con otra red del servidor) y `MICHELITO_REPO`
  (el enlace «Código abierto» de la demo).
- Si el paquete de GHCR es privado, el token del workflow sirve igual: va por stdin,
  `desplegar.sh` lo usa con un `DOCKER_CONFIG` temporal y sale (`docker logout`) al terminar; el
  token vence con el job.

El `known_hosts` para GitHub: en tu máquina, `ssh-keyscan -t ed25519 <ip-o-host-del-vps>`, y
compara la huella con la del servidor (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`, desde
la consola del proveedor) antes de guardarlo como secreto.

## 3. GitHub: environment, secretos y variables

**Obligatorio**: el environment `demo` solo admite la rama `main` (Settings → Environments → demo
→ Deployment branches → «Selected branches» → `main`), y los secretos del VPS van **solo** en ese
environment, nunca a nivel de repositorio: así ningún otro workflow ni rama puede leerlos.

```bash
R=michelito-app/michelito
gh api -X PUT "repos/$R/environments/demo" \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST "repos/$R/environments/demo/deployment-branch-policies" -f name=main -f type=branch

gh secret set VPS_HOST --env demo -R "$R" --body '<ip-o-host-del-vps>'
gh secret set VPS_USER --env demo -R "$R" --body 'deploy'
gh secret set VPS_SSH_KEY --env demo -R "$R" < ./michelito-despliegue
gh secret set VPS_KNOWN_HOSTS --env demo -R "$R" < ./known_hosts_vps
gh variable set MICHELITO_HOST -R "$R" --body 'demo.michelito.app'
```

| Nombre | Dónde | Qué |
|--------|-------|-----|
| `VPS_HOST` | secreto de `demo` | IP o nombre del VPS (el mismo que va en `VPS_KNOWN_HOSTS`) |
| `VPS_USER` | secreto de `demo` | `deploy` |
| `VPS_SSH_KEY` | secreto de `demo` | la llave **privada** `michelito-despliegue` |
| `VPS_KNOWN_HOSTS` | secreto de `demo` | la línea de `ssh-keyscan` verificada |
| `MICHELITO_HOST` | variable del repo | `demo.michelito.app` (es el valor por omisión si no existe) |

Borra la llave privada de tu máquina después de guardarla en GitHub.

Permisos: el workflow de despliegue tiene `packages: write` solo en el job que publica la imagen;
el de despliegue manda al servidor un `GITHUB_TOKEN` con `packages: read`. Las acciones van
fijadas por sha de commit; Dependabot las actualiza cada semana junto con las dependencias y las
imágenes base.

**CodeQL** no tiene archivo en el repositorio: se activa con el «default setup» de GitHub
(Settings → Code security → CodeQL analysis → Default), que analiza Python y JavaScript/TypeScript
en cada PR y push a `main`. Si se agregara un `codeql.yml` («advanced setup»), el default setup
dejaría de correr.

## 4. Qué hace un despliegue

`deploy.yml` corre cuando termina bien el CI de un push a `main` (nunca para un PR):

1. Si mientras corría el CI llegó otro commit a `main`, no hace nada (lo deja dicho en el resumen
   del job): lo desplegará el CI de ese commit nuevo.
2. Construye la imagen, la sube con las etiquetas `<sha>` y `latest` y toma su digest.
3. Por SSH ejecuta en el servidor `desplegar.sh "<sha> <digest>"`, que:
   1. Valida sha, digest y token, ignora que se corte la conexión SSH, y toma un candado (un
      despliegue a la vez; en GitHub tampoco se cancelan despliegues en curso).
   2. Entra a GHCR con el token, baja `ghcr.io/michelito-app/michelito@<digest>` y le pone la
      etiqueta local `<sha>`.
   3. Respalda `opiniones.db` (con la API de respaldo de SQLite, dentro del contenedor) en
      `/opt/michelito/respaldos/`, y conserva los últimos 10. Si hay base y no se puede respaldar,
      no despliega.
   4. Escribe `MICHELITO_TAG` y `MICHELITO_DIGEST` en `.env`, `docker compose up -d`, y espera
      `/api/health` hasta 90 s.
   5. Si no responde, vuelve a la versión que estaba (o, si se redesplegó la misma, a la
      anterior), la levanta y termina con error: el job falla.
   6. Si responde, guarda la que estaba en `etiqueta-anterior`, sale de GHCR y borra las
      imágenes viejas (conserva la actual y la anterior).
4. Comprueba `https://demo.michelito.app/api/health` desde afuera. Esta comprobación **solo
   avisa**: si falla (DNS, certificado, Caddy), el job falla pero la versión nueva queda puesta,
   porque ya respondió por dentro. Revisa `docker compose logs caddy` y, si hace falta, revierte
   (sección 6).

### El primer despliegue

El workflow de despliegue solo existe para GitHub cuando está en `main`, y se dispara al terminar
un CI. Con el servidor y los secretos listos:

- si el repo ya tiene un CI exitoso en `main`, abre en Actions el run de «Despliegue de la demo»
  que se saltó o falló y pulsa *Re-run all jobs* (usa el mismo commit; si ya no es la punta de
  `main`, no desplegará: usa la otra opción);
- o sube un commit nuevo a `main` (aunque sea de documentación): el CI corre y, al pasar, se
  despliega.

## 5. Leer las opiniones

```bash
sudo -u deploy docker compose --project-directory /opt/michelito exec -T app finanzas opiniones --datos /datos
sudo -u deploy docker compose --project-directory /opt/michelito exec -T app finanzas opiniones --datos /datos --uso
sudo -u deploy docker compose --project-directory /opt/michelito exec -T app finanzas opiniones --datos /datos --json > opiniones.json
```

(`sudo -u deploy` porque `.env` es legible solo por `deploy`; la llave de `deploy` no da terminal,
pero el administrador sí puede usar ese usuario con `sudo`.)

## 6. Revertir

- Desde GitHub: Actions → «Despliegue de la demo» → *Run workflow* (rama `main`, acción
  `rollback`). Vuelve a la versión anterior; otro `rollback` vuelve a la de antes.
- En el servidor (sin token: la imagen anterior sigue ahí):
  ```bash
  sudo -u deploy env SSH_ORIGINAL_COMMAND=rollback /opt/michelito/desplegar.sh </dev/null
  ```
- A una versión concreta: haz `git revert` en `main`; el CI y el despliegue hacen el resto.

## 7. Respaldos

- `opiniones.db` se respalda antes de cada despliegue en `/opt/michelito/respaldos/` (los últimos
  10, legibles solo por `deploy`). Uno a mano, con la misma API de SQLite:
  ```bash
  sudo -u deploy docker compose --project-directory /opt/michelito exec -T app python -c \
    "import sqlite3; sqlite3.connect('file:/datos/opiniones.db?mode=ro', uri=True).backup(sqlite3.connect('/tmp/r.db'))"
  sudo -u deploy docker compose --project-directory /opt/michelito cp app:/tmp/r.db /opt/michelito/respaldos/opiniones-a-mano.db
  ```
- Las copias de los visitantes no se respaldan: se borran solas a las 24 h y salen de la
  plantilla.
- Lleva una copia fuera del VPS de vez en cuando (`scp` del último respaldo) o activa los
  snapshots del proveedor.

## 8. Actualizar el sistema

- Ubuntu: `unattended-upgrades` aplica las de seguridad; de vez en cuando
  `sudo apt update && sudo apt full-upgrade` y, si lo pide, `sudo reboot` (los contenedores
  vuelven solos).
- Docker y compose se actualizan con `apt` (repositorio de Docker).
- La imagen de la app y la de Caddy: por los PRs de Dependabot. Un cambio en `Caddyfile` o
  `docker-compose.yml` **no** llega solo al servidor: cópialo a `/opt/michelito` (como en la
  sección 2) y corre
  `sudo -u deploy docker compose --project-directory /opt/michelito up -d` (o `… restart caddy`
  si solo cambió el Caddyfile).

## 9. Más adelante: el proxy de Cloudflare

Si se activa la nube naranja (proxy) de Cloudflare:

1. Las conexiones a Caddy llegarán desde las IP de Cloudflare: sin más cambios, todos los
   visitantes compartirían el cupo de copias por IP. Hay que decirle a **Caddy** que confíe en
   Cloudflare y que tome la IP del cliente de su cabecera, en las opciones globales del
   Caddyfile:
   ```
   servers {
       protocols h1 h2
       trusted_proxies static <rangos de cloudflare.com/ips-v4 y ips-v6>
       client_ip_headers CF-Connecting-IP
   }
   ```
   y, dentro de `reverse_proxy`, `header_up X-Forwarded-For {client_ip}` (sin esa línea, Caddy
   conserva el `X-Forwarded-For` que trae Cloudflare y le suma la IP de Cloudflare al final, que
   es lo que la app tomaría). Así la app sigue recibiendo un solo salto con la IP real, y
   **`--proxy-confiable` / `MICHELITO_RED` no cambian** (la app solo confía en Caddy). Lo que no se
   debe hacer es poner los rangos de Cloudflare en `FINANZAS_DEMO_PROXIES`: la app nunca habla con
   Cloudflare directo.
2. SSL/TLS de Cloudflare en **Full (strict)** (Caddy sigue teniendo su certificado; con el proxy
   activo, el reto HTTP-01 funciona igual).
3. Opcional: cerrar 80/443 en el firewall del proveedor salvo para los rangos de Cloudflare
   (ufw no basta: Docker publica los puertos por fuera de sus reglas).
4. Revisar que la CSP no choque con lo que Cloudflare inyecte (Rocket Loader, analítica: mejor
   desactivados).
