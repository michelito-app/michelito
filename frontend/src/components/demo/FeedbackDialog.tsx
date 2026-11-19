import { useState } from 'react'
import { useLocation } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { OPINION_MAX, opinionBody, opinionProblem, refFrom, sendOpinion, useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

// El `?ref=` de la URL con que se entró (se guarda con cada opinión).
const ENTRY_REF = typeof window === 'undefined' ? null : refFrom(window.location.search)

/** «Opinar»: texto y correo opcional; página, ancho, versión, fecha y `ref` van solos. */
export function FeedbackDialog({ onClose }: { onClose: () => void }) {
  const mode = useMode()
  const location = useLocation()
  const [text, setText] = useState('')
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    const problem = opinionProblem(text, email)
    if (problem) {
      setError(problem)
      return
    }
    setState('sending')
    setError(null)
    const context = {
      path: location.pathname,
      width: window.innerWidth,
      version: mode.version,
      ref: ENTRY_REF,
    }
    try {
      await sendOpinion(opinionBody(text, email, context))
      setState('sent')
    } catch (failure) {
      setState('idle')
      setError((failure as Error).message)
    }
  }

  if (state === 'sent') {
    return (
      <Modal title="¡Gracias!" onClose={onClose}>
        <p role="status" className="text-sm">
          Tu opinión llegó. Cada una se lee.
        </p>
        <Button className="h-11 self-end px-4" onClick={onClose}>
          Cerrar
        </Button>
      </Modal>
    )
  }
  return (
    <Modal title="Opinar" onClose={onClose}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          ¿Qué te pareció? ¿Qué falta o sobra?
          <textarea
            value={text}
            maxLength={OPINION_MAX}
            rows={5}
            onChange={(event) => setText(event.target.value)}
            className={cn(
              'w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base font-normal md:text-sm',
              FOCUS,
            )}
          />
        </label>
        <p className="-mt-2 text-right text-xs text-muted-foreground">
          {text.length.toLocaleString('en-US')} / {OPINION_MAX.toLocaleString('en-US')}
        </p>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Correo (opcional, solo si quieres respuesta)
          <Input
            type="email"
            value={email}
            autoComplete="email"
            onChange={(event) => setEmail(event.target.value)}
            className="h-11"
          />
        </label>
        <p className="text-xs text-muted-foreground">
          Se envía también la pantalla en que estás, el ancho de la ventana, la versión y la
          fecha. Nada más.
        </p>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="h-11 self-end px-4" disabled={state === 'sending'}>
          {state === 'sending' ? 'Enviando…' : 'Enviar opinión'}
        </Button>
      </form>
    </Modal>
  )
}
