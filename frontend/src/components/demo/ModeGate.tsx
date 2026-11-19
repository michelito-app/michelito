import { type ReactNode, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { type ModeInfo, ModeContext, fetchMode, isDemo, startSession } from '@/lib/demo'

type Boot =
  | { state: 'loading' }
  | { state: 'ready'; mode: ModeInfo }
  | { state: 'failed'; message: string }

/** Asks for the mode before showing the app. In the demo, when the visitor has no copy yet, it
 * asks for one (`POST /api/demo/session`) before any screen asks for data. When the server knows
 * nothing about modes (404: an old one) it goes on as local; another error shows a retry. */
export function ModeGate({ children }: { children: ReactNode }) {
  const [boot, setBoot] = useState<Boot>({ state: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let alive = true
    async function load() {
      const mode = await fetchMode()
      if (isDemo(mode) && !mode.session) await startSession()
      if (alive) setBoot({ state: 'ready', mode: { ...mode, session: true } })
    }
    load().catch((error: Error) => {
      if (alive) setBoot({ state: 'failed', message: error.message })
    })
    return () => {
      alive = false
    }
  }, [attempt])

  useEffect(() => {
    if (boot.state === 'ready' && isDemo(boot.mode) && boot.mode.name) {
      document.title = t('demo.titleSuffix', { name: boot.mode.name })
    }
  }, [boot])

  if (boot.state === 'loading') {
    return (
      <p role="status" className="p-10 text-sm text-muted-foreground">
        {t('demo.gate.loading')}
      </p>
    )
  }
  if (boot.state === 'failed') {
    return (
      <div role="alert" className="mx-auto flex max-w-md flex-col gap-4 p-10">
        <p className="text-base font-semibold">{t('demo.gate.failed')}</p>
        <p className="text-sm text-muted-foreground">{boot.message}</p>
        <Button className="h-11 self-start px-4" onClick={() => setAttempt((n) => n + 1)}>
          {t('demo.gate.retry')}
        </Button>
      </div>
    )
  }
  return <ModeContext.Provider value={boot.mode}>{children}</ModeContext.Provider>
}
