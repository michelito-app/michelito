import { ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { UploadFlow } from '@/components/onboarding/UploadFlow'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { useMode } from '@/lib/demo'
import { signOut } from '@/lib/hosted'
import { cn } from '@/lib/utils'

const LINK = cn(
  'inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-ink-2 no-underline hover:bg-muted',
  FOCUS,
)

/** Hosted mode before the first statement squares: the whole screen is this welcome and upload
 * flow. No app shell, no bottom bar and no other route: any address shows it (and is replaced by
 * the root, so the Summary is where it lands once the gate opens). */
export function Gate() {
  const mode = useMode()
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    if (pathname !== '/' && pathname !== '/import') navigate({ pathname: '/', search }, { replace: true })
  }, [pathname, search, navigate])

  async function leave() {
    setLeaving(true)
    try {
      await signOut()
    } finally {
      window.location.assign('/')
    }
  }

  return (
    <main
      aria-label={t('onboarding.gate.label')}
      data-gate=""
      className="mx-auto flex min-h-dvh w-full max-w-xl flex-col gap-6 px-4 py-8 sm:py-12"
    >
      <header className="flex flex-col gap-3">
        <h1 className="text-[28px] font-bold tracking-[-0.02em] sm:text-[32px]">
          {t('onboarding.gate.title')}
        </h1>
        <p className="text-base text-ink-2">{t('onboarding.gate.lead')}</p>
        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-primary" aria-hidden="true" />
          {t('onboarding.gate.trust')}
        </p>
      </header>
      <UploadFlow demoUrl={mode.demo_url} />
      <footer className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
        {mode.demo_url && (
          <a href={mode.demo_url} className={LINK}>
            {t('onboarding.gate.demo')}
          </a>
        )}
        <button type="button" className={LINK} disabled={leaving} onClick={() => void leave()}>
          {t('onboarding.gate.signOut')}
        </button>
      </footer>
    </main>
  )
}
