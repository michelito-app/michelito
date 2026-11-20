import { useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useCallback, useEffect, useState } from 'react'
import { SignedOut } from '@/components/hosted/SignedOut'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { SIGNED_OUT_EVENT } from '@/lib/api'
import { type ModeInfo, ModeContext, fetchMode, isDemo, isHosted, startSession } from '@/lib/demo'
import { takeLinkToken } from '@/lib/hosted'

type Boot =
  | { state: 'loading' }
  | { state: 'ready'; mode: ModeInfo }
  | { state: 'failed'; message: string }

/** Asks for the mode before showing the app. In the demo, when the visitor has no copy yet, it
 * asks for one (`POST /api/demo/session`) before any screen asks for data. When the server knows
 * nothing about modes (404: an old one) it goes on as local; another error shows a retry. In
 * hosted mode without a session it shows the signed-out page and the sign-in instead of the app;
 * when a session ends (any 401) it forgets every cached answer and asks again. */
// The desktop link is taken out of the address once per page load, whatever the mode or session
// (a StrictMode double render must not lose it).
let taken: { token: string | null } | null = null
function initialLink(): string | null {
  taken ??= { token: takeLinkToken() }
  return taken.token
}

export function ModeGate({ children }: { children: ReactNode }) {
  const [link] = useState(initialLink)
  const [boot, setBoot] = useState<Boot>({ state: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let alive = true
    async function load() {
      const mode = await fetchMode()
      if (isDemo(mode) && !mode.session) await startSession()
      const session = isHosted(mode) ? mode.session : true
      if (alive) setBoot({ state: 'ready', mode: { ...mode, session } })
    }
    load().catch((error: Error) => {
      if (alive) setBoot({ state: 'failed', message: error.message })
    })
    return () => {
      alive = false
    }
  }, [attempt])

  const queryClient = useQueryClient()
  // Hosted: another account's (or no) data must never stay on screen after a session changes.
  const reload = useCallback(() => {
    queryClient.clear()
    setAttempt((n) => n + 1)
  }, [queryClient])
  const signedIn = boot.state === 'ready' && isHosted(boot.mode) && boot.mode.session

  useEffect(() => {
    if (!signedIn) return
    window.addEventListener(SIGNED_OUT_EVENT, reload)
    return () => window.removeEventListener(SIGNED_OUT_EVENT, reload)
  }, [signedIn, reload])

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
  if (isHosted(boot.mode) && !boot.mode.session) {
    return <SignedOut mode={boot.mode} link={link} onSignedIn={reload} />
  }
  return <ModeContext.Provider value={boot.mode}>{children}</ModeContext.Provider>
}
