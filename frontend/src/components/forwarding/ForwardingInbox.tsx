import { useQueryClient } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import { type FormEvent, type ReactNode, useId, useState } from 'react'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import {
  type Approval,
  type Forwarding,
  type Quarantined,
  UNLOCK_BANKS,
  type UnlockBank,
  type WaitingStatement,
  approveHeld,
  approveQuarantined,
  discardHeld,
  discardQuarantined,
  forwardingKey,
  shortDate,
  undoApproval,
  unlockWaiting,
  waitingReason,
} from '@/lib/forwarding'
import { bankName, onboardingKey } from '@/lib/onboarding'
import { cn } from '@/lib/utils'

/** What waits for the person: locked statements (the password form), statements of a new
 * account and unverified emails (approve after an explicit second step, or discard), and what
 * entered by approval (marked, and it can be taken back). */
export function ForwardingInbox({ data }: { data: Forwarding }) {
  const locked = data.waiting.filter((item) => item.state !== 'approval')
  const held = data.waiting.filter((item) => item.state === 'approval')
  return (
    <>
      {locked.length > 0 && <Waiting items={locked} />}
      {held.length > 0 && <Held items={held} />}
      {data.quarantine.length > 0 && <Quarantine items={data.quarantine} />}
      {data.approvals.length > 0 && <Approvals items={data.approvals} />}
    </>
  )
}

function useRefresh() {
  const client = useQueryClient()
  return async () => {
    await client.invalidateQueries({ queryKey: forwardingKey })
    await client.invalidateQueries({ queryKey: onboardingKey })
    // New statements change every figure: everything else is fetched again too.
    await client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
  }
}

/** Runs one action at a time and keeps its error. */
function useAction() {
  const refresh = useRefresh()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function act(work: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await work()
      await refresh()
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, act }
}

function Panel({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <h3 id={id} className={PANEL_TITLE}>
        {title}
      </h3>
      <p className="text-sm text-ink-2">{lead}</p>
      {children}
    </section>
  )
}

function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null
  return (
    <p role="alert" className="text-sm text-destructive">
      {error}
    </p>
  )
}

function Waiting({ items }: { items: WaitingStatement[] }) {
  const banks = UNLOCK_BANKS.filter((bank) => items.some((item) => item.bank === bank))
  const [bank, setBank] = useState<UnlockBank>(banks[0] ?? 'popular')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null)
  const refresh = useRefresh()
  const id = useId()

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!password) return
    setBusy(true)
    setMessage(null)
    try {
      const done = await unlockWaiting(bank, password)
      setMessage(
        done.opened > 0
          ? { text: t('forwarding.waiting.opened', { count: done.opened }), ok: true }
          : { text: t('forwarding.waiting.notOpened', { bank: bankName(bank) }), ok: false },
      )
      await refresh()
    } catch (failure) {
      setMessage({ text: (failure as Error).message, ok: false })
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <Panel title={t('forwarding.waiting.title')} lead={t('forwarding.waiting.lead')}>
      <ul className="flex flex-col">
        {items.map((item) => (
          <li
            key={item.id}
            data-waiting-reason={item.reason}
            className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 last:border-b-0"
          >
            <span className="text-sm font-medium">
              {t('forwarding.waiting.item', { bank: bankName(item.bank), date: shortDate(item.received_at) })}
            </span>
            <span className="text-[13px] text-muted-foreground">{waitingReason(item)}</span>
          </li>
        ))}
      </ul>
      {message && (
        <p role={message.ok ? 'status' : 'alert'} className={cn('text-sm', message.ok ? 'text-down' : 'text-destructive')}>
          {message.text}
        </p>
      )}
      <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
        <label htmlFor={`${id}-bank`} className="flex flex-col gap-1 text-sm font-medium">
          {t('forwarding.waiting.bank')}
          <select
            id={`${id}-bank`}
            value={bank}
            onChange={(event) => setBank(event.target.value as UnlockBank)}
            className={cn('h-11 rounded-lg border border-input bg-card px-2 text-sm', FOCUS)}
          >
            {(banks.length ? banks : UNLOCK_BANKS).map((key) => (
              <option key={key} value={key}>
                {bankName(key)}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={`${id}-password`} className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm font-medium">
          {t('forwarding.waiting.password')}
          <Input
            id={`${id}-password`}
            type="password"
            autoComplete="off"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="h-11"
          />
        </label>
        <Button type="submit" className="h-11 px-5" disabled={busy || !password}>
          {busy ? t('forwarding.waiting.trying') : t('forwarding.waiting.submit')}
        </Button>
      </form>
    </Panel>
  )
}

interface DecisionProps {
  busy: boolean
  warnings: string[]
  onApprove: () => void
  onDiscard: () => void
}

/** «Aprobar» opens a second step that says what approving means (and any warning) before
 * anything is opened; «Descartar» deletes at once. */
function Decision({ busy, warnings, onApprove, onDiscard }: DecisionProps) {
  const [asking, setAsking] = useState(false)
  if (!asking) {
    return (
      <div className="flex gap-2">
        <Button className="h-11 px-4" disabled={busy} onClick={() => setAsking(true)}>
          {t('forwarding.quarantine.approve')}
        </Button>
        <Button variant="outline" className="h-11 px-4" disabled={busy} onClick={onDiscard}>
          {t('forwarding.quarantine.discard')}
        </Button>
      </div>
    )
  }
  return (
    <div role="alertdialog" aria-label={t('forwarding.quarantine.approve')} className="flex flex-col gap-2 rounded-xl bg-muted px-3 py-3">
      {warnings.map((warning) => (
        <p key={warning} className="flex items-start gap-1.5 text-sm font-medium text-destructive">
          <ShieldAlert size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
          {warning}
        </p>
      ))}
      <p className="text-sm text-ink-2">{t('forwarding.quarantine.confirmLead')}</p>
      <div className="flex gap-2">
        <Button variant="destructive" className="h-11 px-4" disabled={busy} onClick={onApprove}>
          {t('forwarding.quarantine.confirm')}
        </Button>
        <Button variant="ghost" className="h-11 px-4" onClick={() => setAsking(false)}>
          {t('forwarding.quarantine.cancel')}
        </Button>
      </div>
    </div>
  )
}

function Held({ items }: { items: WaitingStatement[] }) {
  const { busy, error, act } = useAction()
  return (
    <Panel title={t('forwarding.held.title')} lead={t('forwarding.held.lead')}>
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={item.id} data-held-item className="flex flex-col gap-2 border-b border-border py-2 last:border-b-0">
            <span className="text-sm font-medium">
              {t('forwarding.held.item', { bank: bankName(item.bank), date: shortDate(item.received_at) })}
            </span>
            <Decision
              busy={busy}
              warnings={[t('forwarding.quarantine.otherCard')]}
              onApprove={() => void act(() => approveHeld(item.id))}
              onDiscard={() => void act(() => discardHeld(item.id))}
            />
          </li>
        ))}
      </ul>
      <ErrorLine error={error} />
    </Panel>
  )
}

function warningsOf(item: Quarantined): string[] {
  const found: string[] = []
  if (item.reason === 'unknown_card') found.push(t('forwarding.quarantine.otherCard'))
  else if (item.claims_bank) found.push(t('forwarding.quarantine.impersonation'))
  return found
}

function Quarantine({ items }: { items: Quarantined[] }) {
  const { busy, error, act } = useAction()
  return (
    <Panel title={t('forwarding.quarantine.title')} lead={t('forwarding.quarantine.lead')}>
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={item.id} data-quarantine-item className="flex flex-col gap-2 border-b border-border py-2 last:border-b-0">
            <div className="flex min-w-0 flex-col">
              <span className="break-all text-sm font-medium">
                {t('forwarding.quarantine.item', { domain: item.sender_domain, date: shortDate(item.received_at) })}
              </span>
              <span className="text-[13px] text-muted-foreground">
                {t(`forwarding.quarantine.${item.reason}`)} ·{' '}
                {t('forwarding.quarantine.attachments', { count: item.attachments })}
              </span>
            </div>
            <Decision
              busy={busy}
              warnings={warningsOf(item)}
              onApprove={() => void act(() => approveQuarantined(item.id))}
              onDiscard={() => void act(() => discardQuarantined(item.id))}
            />
          </li>
        ))}
      </ul>
      <ErrorLine error={error} />
    </Panel>
  )
}

function Approvals({ items }: { items: Approval[] }) {
  const { busy, error, act } = useAction()
  return (
    <Panel title={t('forwarding.approvals.title')} lead={t('forwarding.approvals.lead')}>
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={item.id} data-approval-item className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 last:border-b-0">
            <span className="break-all text-sm font-medium">
              {t(item.kind === 'alert' ? 'forwarding.approvals.alert' : 'forwarding.approvals.statement', {
                domain: item.sender_domain,
                date: shortDate(item.approved_at),
              })}
            </span>
            <Button variant="outline" className="h-11 px-4" disabled={busy} onClick={() => void act(() => undoApproval(item.id))}>
              {t('forwarding.approvals.undo')}
            </Button>
          </li>
        ))}
      </ul>
      <ErrorLine error={error} />
    </Panel>
  )
}
