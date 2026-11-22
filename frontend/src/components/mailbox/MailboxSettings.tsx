import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Mail, RefreshCw } from 'lucide-react'
import { type ReactNode, useEffect, useId, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  type MailboxStatus,
  disconnect,
  lastReadLine,
  mailboxKey,
  mailboxView,
  outcomeIsGood,
  outcomeMessage,
  outcomeOf,
  startConnect,
  syncNow,
  useMailbox,
  withoutOutcome,
} from '@/lib/mailbox'
import { cn } from '@/lib/utils'

const SECTION_ID = 'mailbox'
const LINK = cn('inline-flex min-h-11 items-center text-sm font-semibold text-primary underline-offset-4 hover:underline', FOCUS)

interface Notice {
  text: string
  good: boolean
}

/** Settings → Gmail (hosted, only when the server offers it): connect the person's own Gmail,
 * read-only, for the merchants' receipts; see when it was read; read now; disconnect. The
 * outcome Google's callback leaves in the address (`?gmail=…`) is shown once and removed. */
export function MailboxSettings() {
  const mailbox = useMailbox()
  const [notice, setNotice] = useOutcomeNotice()
  const view = mailboxView(mailbox.data)

  // Back from Google: bring the section (and its message) into view once it is there.
  useEffect(() => {
    if (notice && view !== 'hidden') document.getElementById(SECTION_ID)?.scrollIntoView?.({ block: 'start' })
  }, [notice, view])

  if (mailbox.error) {
    return (
      <Section>
        <LoadError what={t('mailbox.what')} error={mailbox.error} onRetry={() => void mailbox.refetch()} />
      </Section>
    )
  }
  if (!mailbox.data || view === 'hidden') return null
  return (
    <Section>
      {notice && <NoticeLine notice={notice} />}
      {view === 'disconnected' ? (
        <Disconnected onError={(text) => setNotice({ text, good: false })} />
      ) : (
        <Connected status={mailbox.data} reconnect={view === 'reconnect'} failed={view === 'failed'} onNotice={setNotice} />
      )}
    </Section>
  )
}

/** The callback's outcome, read once from the address (when Settings opens) and then removed
 * from it. */
function useOutcomeNotice(): [Notice | null, (notice: Notice | null) => void] {
  const location = useLocation()
  const navigate = useNavigate()
  const [notice, setNotice] = useState<Notice | null>(() => {
    const outcome = outcomeOf(location.search)
    return outcome ? { text: outcomeMessage(outcome), good: outcomeIsGood(outcome) } : null
  })

  useEffect(() => {
    if (!outcomeOf(location.search)) return
    void navigate({ search: withoutOutcome(location.search), hash: location.hash }, { replace: true })
  }, [location.search, location.hash, navigate])

  return [notice, setNotice]
}

function Section({ children }: { children: ReactNode }) {
  return (
    <section id={SECTION_ID} aria-labelledby="settings-mailbox" className="flex scroll-mt-20 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="settings-mailbox" className="text-lg font-semibold">
          {t('mailbox.title')}
        </h2>
        <p className="text-sm text-muted-foreground">{t('mailbox.lead')}</p>
      </div>
      {children}
      <a href="/privacy" className={cn(LINK, 'self-start')}>
        {t('mailbox.privacy')}
      </a>
    </section>
  )
}

function NoticeLine({ notice }: { notice: Notice }) {
  return (
    <p
      role={notice.good ? 'status' : 'alert'}
      className={cn('rounded-xl px-4 py-3 text-sm', notice.good ? 'bg-muted text-ink-2' : 'bg-destructive/10 text-destructive')}
    >
      {notice.text}
    </p>
  )
}

/** Goes to Google's consent page (the server made it, with a single-use state). */
function useConnect(onError: (text: string) => void) {
  const [busy, setBusy] = useState(false)
  async function connect() {
    setBusy(true)
    try {
      window.location.assign(await startConnect())
    } catch (failure) {
      setBusy(false)
      onError(failure instanceof Error ? failure.message : String(failure))
    }
  }
  return { busy, connect }
}

function Disconnected({ onError }: { onError: (text: string) => void }) {
  const { busy, connect } = useConnect(onError)
  return (
    <div className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <Button className="h-11 self-start px-5" disabled={busy} onClick={() => void connect()}>
        <Mail size={16} aria-hidden="true" />
        {busy ? t('mailbox.opening') : t('mailbox.connect')}
      </Button>
    </div>
  )
}

interface ConnectedProps {
  status: MailboxStatus
  reconnect: boolean
  failed: boolean
  onNotice: (notice: Notice | null) => void
}

function Connected({ status, reconnect, failed, onNotice }: ConnectedProps) {
  const client = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const { busy: opening, connect } = useConnect((text) => onNotice({ text, good: false }))
  const id = useId()

  async function act(action: () => Promise<Notice | null>) {
    setBusy(true)
    try {
      onNotice(await action())
    } catch (failure) {
      onNotice({ text: failure instanceof Error ? failure.message : String(failure), good: false })
    } finally {
      setBusy(false)
      await client.invalidateQueries({ queryKey: mailboxKey })
    }
  }

  const readNow = () =>
    act(async () => {
      await syncNow()
      return { text: t('mailbox.syncStarted'), good: true }
    })

  const leave = () =>
    act(async () => {
      const after = await disconnect()
      setAsking(false)
      return after.revoked
        ? { text: t('mailbox.disconnected'), good: true }
        : { text: t('mailbox.disconnectedNotRevoked'), good: false }
    })

  return (
    <div className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <div className="flex flex-col gap-0.5">
        <h3 id={id} className={PANEL_TITLE}>
          {t('mailbox.connected')}
        </h3>
        {status.address && (
          <p aria-labelledby={id} data-mailbox-address className="break-all font-mono text-[15px]">
            {status.address}
          </p>
        )}
      </div>
      {reconnect && (
        <div role="alert" className="flex flex-col gap-2 rounded-xl bg-destructive/10 px-4 py-3">
          <p className="flex items-start gap-1.5 text-sm font-semibold text-destructive">
            <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
            {t('mailbox.reconnect.title')}
          </p>
          <p className="text-sm text-ink-2">{t('mailbox.reconnect.lead')}</p>
          <Button className="h-11 self-start px-5" disabled={opening} onClick={() => void connect()}>
            {opening ? t('mailbox.opening') : t('mailbox.reconnect.action')}
          </Button>
        </div>
      )}
      {failed && <p className="text-sm text-muted-foreground">{t('mailbox.failed')}</p>}
      <div className="flex flex-col gap-1 text-sm text-ink-2">
        <p role="status" aria-live="polite">
          {lastReadLine(status)}
        </p>
        <p>{t('mailbox.receipts', { count: status.receipts })}</p>
        <p className="text-xs text-muted-foreground">{t('mailbox.hourly')}</p>
      </div>
      {asking ? (
        <div role="alertdialog" aria-label={t('mailbox.disconnect')} className="flex flex-col gap-2 rounded-xl bg-muted px-3 py-3">
          <p className="text-sm text-ink-2">{t('mailbox.disconnectLead')}</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="destructive" className="h-11 px-4" disabled={busy} onClick={() => void leave()}>
              {t('mailbox.disconnectYes')}
            </Button>
            <Button variant="ghost" className="h-11 px-4" onClick={() => setAsking(false)}>
              {t('mailbox.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row">
          {!reconnect && (
            <Button variant="outline" className="h-11 px-4" disabled={busy || status.syncing} onClick={() => void readNow()}>
              <RefreshCw size={16} aria-hidden="true" />
              {t('mailbox.syncNow')}
            </Button>
          )}
          <Button variant="ghost" className="h-11 px-4" disabled={busy} onClick={() => setAsking(true)}>
            {t('mailbox.disconnect')}
          </Button>
        </div>
      )}
    </div>
  )
}
