"""De dónde sale la base de cada petición: el *proveedor de base* del board.

`create_app` ya no abre una ruta fija: antes de cada petición le pregunta al proveedor qué
`Workspace` (base y titulares) le toca, y `connection()` abre ese. Así el mismo FastAPI sirve:

- el board local (`FixedProvider`): siempre la base y los titulares de la carpeta de datos;
- la demo pública (`finanzas.demo.copias.DemoProvider`): la copia del visitante según su cookie;
- en la fase 2, la base del usuario autenticado (otro proveedor con la misma interfaz).

Una petición sin `Workspace` (sin sesión de la demo) no abre ninguna base: `connection()` responde
401 y nada se escribe en ninguna.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from starlette.requests import Request
from starlette.responses import Response


@dataclass(frozen=True)
class Workspace:
    """La base de una petición y su archivo de titulares."""

    database: Path
    holders: Path


@dataclass(frozen=True)
class Resolution:
    """Lo que el proveedor decidió para una petición.

    `workspace`: la base que le toca (None: ninguna). `refusal`: una respuesta que corta la
    petición antes de llegar a la ruta (p. ej. demasiadas peticiones). `finish`: se llama (en un
    hilo, fuera del bucle de eventos) con la respuesta de la ruta, p. ej. para contar un uso.
    `release`: se llama siempre al terminar la petición (p. ej. suelta un turno de trabajo)."""

    workspace: Workspace | None
    refusal: Response | None = None
    finish: Callable[[Response], None] | None = None
    release: Callable[[], None] | None = None


class WorkspaceProvider(Protocol):
    async def resolve(self, request: Request) -> Resolution:
        """La base de esta petición (lo llama un middleware, antes de la ruta). Lo que toque el
        disco va en un hilo: no debe frenar el bucle de eventos."""
        ...

    def has_session(self, request: Request) -> bool:
        """Si la petición ya tiene base propia (en local, siempre)."""
        ...


@dataclass(frozen=True)
class FixedProvider:
    """El board local: siempre la misma base y los mismos titulares."""

    workspace: Workspace

    async def resolve(self, request: Request) -> Resolution:
        return Resolution(self.workspace)

    def has_session(self, request: Request) -> bool:
        return True


CURRENT: ContextVar[Workspace | None] = ContextVar("finanzas_workspace", default=None)


Register = Callable[..., None]
OnConnect = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Mode:
    """Lo que cambia entre el board local y la demo pública (ver `create_app`).

    `name`: «local» o «demo». `allowed_hosts`: los que acepta `TrustedHostMiddleware`.
    `authors`: los `X-Finanzas-Autor` aceptados (en la demo, solo el usuario). `blocked`:
    prefijos de rutas que responden 403. `max_body`: bytes máximos del cuerpo (None: sin tope).
    `info`: lo que `GET /api/modo` cuenta a la interfaz. `register(app, connection, load_flow)`:
    rutas propias del modo, antes de la de «no existe». `on_connect`: se aplica a cada conexión
    que abre `connection()` (en la demo, el tope de tamaño de la copia)."""

    name: str
    provider: WorkspaceProvider
    allowed_hosts: tuple[str, ...]
    authors: tuple[str, ...]
    blocked: tuple[str, ...] = ()
    max_body: int | None = None
    info: dict[str, str] | None = None
    register: Register | None = None
    on_connect: OnConnect | None = None
