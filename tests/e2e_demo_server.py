"""Servidor de la demo para las pruebas e2e (datos inventados del generador).

Uso: `uv run python -m tests.e2e_demo_server --port 8600`. La carpeta de la demo (plantilla,
copias, opiniones.db) es temporal y se borra al salir (uvicorn termina bien con SIGINT y SIGTERM);
si el proceso muere sin poder limpiar (SIGKILL), la próxima corrida borra las carpetas de
servidores que ya no viven (`_clean_orphans`, por el PID guardado en cada una). La cookie va sin
Secure (http local) y los cupos son altos (todas las pruebas llegan desde 127.0.0.1). Nunca toca
datos reales.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import uvicorn

from finanzas import cli
from finanzas.demo.app import Settings, create_demo_app
from finanzas.demo.copias import Limits

PREFIX = "finanzas-demo-e2e-"
PID_FILE = "servidor.pid"
ORPHAN_AFTER = 600.0  # segundos: una carpeta sin PID más vieja que esto quedó huérfana


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clean_orphans() -> None:
    """Borra las carpetas de servidores de prueba anteriores que ya no corren."""
    for folder in Path(tempfile.gettempdir()).glob(f"{PREFIX}*"):
        pid_file = folder / PID_FILE
        try:
            pid: int | None = int(pid_file.read_text())
        except (OSError, ValueError):
            pid = None
        if pid is None:  # sin PID: recién creada por otro, o de una versión vieja si es vieja
            orphan = time.time() - folder.stat().st_mtime > ORPHAN_AFTER
        else:
            orphan = not _alive(pid)
        if orphan:
            shutil.rmtree(folder, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    _clean_orphans()
    with tempfile.TemporaryDirectory(prefix=PREFIX) as directory:
        (Path(directory) / PID_FILE).write_text(str(os.getpid()))
        settings = Settings(
            data=Path(directory),
            public_host="demo.example",
            secure_cookie=False,
            repo="https://example.com/michelito",
            limits=Limits(per_ip=500, max_live=500, per_minute_new=500, per_minute=10_000),
        )
        app = create_demo_app(settings, cli.STATIC_DIR)
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            app.state.maintenance.stop()


if __name__ == "__main__":
    main()
