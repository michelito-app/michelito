import { useQuery } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { ApiError } from '@/lib/api'
import { decide, fetchRequest } from '@/lib/connector'
import { fetchMe } from '@/lib/hosted'
import { cn } from '@/lib/utils'

/** The consent screen (`/connect?request=…`, hosted): an MCP client (Claude) asks to connect to
 * the signed-in account. It says who asks, where the person goes back to and what the connection
 * can and cannot do; allowing or cancelling sends the person back to the client. */
export function ConnectPage() {
  const [params] = useSearchParams()
  const id = params.get('request') ?? ''
  const asked = useQuery({ queryKey: ['connector', 'request', id], queryFn: () => fetchRequest(id), enabled: id !== '' })
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: fetchMe })
  const [leaving, setLeaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  async function answer(approve: boolean) {
    setFailure(null)
    setLeaving(true)
    try {
      window.location.assign(await decide(id, approve))
    } catch (error) {
      setLeaving(false)
      setFailure(error instanceof Error ? error.message : String(error))
    }
  }

  const gone = id === '' || (asked.error instanceof ApiError && asked.error.status === 404)
  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-5 px-4 py-10">
      {gone ? (
        <p role="alert" className={cn(PANEL, 'px-5 py-4 text-sm text-ink-2')}>
          {t('connector.consent.gone')}
        </p>
      ) : asked.error ? (
        <LoadError what={t('connector.consent.what')} error={asked.error} onRetry={() => void asked.refetch()} />
      ) : !asked.data ? (
        <Skeleton className="h-[360px] rounded-2xl" />
      ) : (
        <section aria-labelledby="connect-title" className={cn(PANEL, 'flex flex-col gap-4 px-5 py-6 sm:px-6')}>
          <div className="flex flex-col gap-1">
            <h1 id="connect-title" className="text-xl font-semibold tracking-tight">
              {t('connector.consent.title', { client: asked.data.client_name })}
            </h1>
            <p className="text-sm text-muted-foreground" data-testid="connect-host">
              {t('connector.consent.back', { host: asked.data.redirect_host })}
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <p className="text-sm font-semibold">{t('connector.consent.can')}</p>
            <ul className="flex flex-col gap-2 text-sm text-ink-2">
              <Line good text={t('connector.consent.read')} />
              <Line good text={t('connector.consent.propose')} />
              <Line good={false} text={t('connector.consent.cannot')} />
            </ul>
          </div>
          <p className="text-xs text-muted-foreground">{t('connector.consent.lasts')}</p>
          {me.data && (
            <p className="text-sm text-ink-2" data-testid="connect-account">
              {t('connector.consent.account', { email: me.data.email })}
            </p>
          )}
          <p className="rounded-xl bg-muted px-4 py-3 text-sm text-ink-2">{t('connector.consent.onlyIf')}</p>
          {failure && (
            <p role="alert" className="rounded-xl bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {failure}
            </p>
          )}
          {leaving ? (
            <p role="status" className="text-sm text-ink-2">
              {t('connector.consent.leaving', { host: asked.data.redirect_host })}
            </p>
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row-reverse sm:justify-start">
              <Button className="h-11 px-6" onClick={() => void answer(true)}>
                {t('connector.consent.allow')}
              </Button>
              <Button variant="ghost" className="h-11 px-4" onClick={() => void answer(false)}>
                {t('connector.consent.deny')}
              </Button>
            </div>
          )}
        </section>
      )}
    </main>
  )
}

function Line({ good, text }: { good: boolean; text: string }) {
  const Icon = good ? Check : X
  return (
    <li className="flex items-start gap-2">
      <Icon size={16} aria-hidden="true" className={cn('mt-0.5 shrink-0', good ? 'text-primary' : 'text-muted-foreground')} />
      <span>{text}</span>
    </li>
  )
}
