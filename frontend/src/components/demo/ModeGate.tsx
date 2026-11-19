import { type ReactNode, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { type ModeInfo, ModeContext, fetchMode, isDemo, startSession } from '@/lib/demo'

type Boot =
  | { state: 'loading' }
  | { state: 'ready'; mode: ModeInfo }
  | { state: 'failed'; message: string }

/** Pregunta el modo antes de mostrar la app. En la demo, si el visitante aún no tiene su copia,
 * la pide (`POST /api/demo/sesion`) antes de que ninguna pantalla pida datos. Si el servidor no
 * sabe de modos (404: uno viejo), se sigue como local; otro error muestra un reintento. */
export function ModeGate({ children }: { children: ReactNode }) {
  const [boot, setBoot] = useState<Boot>({ state: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let alive = true
    async function load() {
      const mode = await fetchMode()
      if (isDemo(mode) && !mode.sesion) await startSession()
      if (alive) setBoot({ state: 'ready', mode: { ...mode, sesion: true } })
    }
    load().catch((error: Error) => {
      if (alive) setBoot({ state: 'failed', message: error.message })
    })
    return () => {
      alive = false
    }
  }, [attempt])

  useEffect(() => {
    if (boot.state === 'ready' && isDemo(boot.mode) && boot.mode.nombre) {
      document.title = `${boot.mode.nombre} · demo`
    }
  }, [boot])

  if (boot.state === 'loading') {
    return (
      <p role="status" className="p-10 text-sm text-muted-foreground">
        Cargando…
      </p>
    )
  }
  if (boot.state === 'failed') {
    return (
      <div role="alert" className="mx-auto flex max-w-md flex-col gap-4 p-10">
        <p className="text-base font-semibold">No se pudo abrir la app.</p>
        <p className="text-sm text-muted-foreground">{boot.message}</p>
        <Button className="h-11 self-start px-4" onClick={() => setAttempt((n) => n + 1)}>
          Reintentar
        </Button>
      </div>
    )
  }
  return <ModeContext.Provider value={boot.mode}>{children}</ModeContext.Provider>
}
