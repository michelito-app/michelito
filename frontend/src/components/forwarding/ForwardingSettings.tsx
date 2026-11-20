import { useQueryClient } from '@tanstack/react-query'
import { Copy, RefreshCw } from 'lucide-react'
import { type FormEvent, useId, useState } from 'react'
import { Link } from 'react-router'
import { ForwardingInbox } from '@/components/forwarding/ForwardingInbox'
import { StepUpSheet } from '@/components/hosted/StepUpSheet'
import { LoadError } from '@/components/LoadError'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import {
  type Confirmation,
  type Forwarding,
  createAddress,
  dismissConfirmation,
  forgetPassword,
  forwardingKey,
  rotateAddress,
  safeGmailLink,
  storePassword,
  useForwarding,
} from '@/lib/forwarding'
import { needsStepUp } from '@/lib/hosted'
import { SUPPORTED_BANKS, type SupportedBank, bankName } from '@/lib/onboarding'
import { cn } from '@/lib/utils'

type Action = () => Promise<void>

/** Settings, "automate the next ones" (hosted): the forwarding address (create, copy, rotate
 * after a fresh verification), Gmail's confirmation code (shown only: the person confirms in
 * Gmail), the waiting statements and quarantine, and the stored PDF passwords. */
export function ForwardingSettings({ email }: { email: string }) {
  const forwarding = useForwarding()
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState<Action | null>(null)

  /** Runs an action; when it needs a fresh verification, asks for it and runs it again. */
  async function run(action: Action) {
    setError(null)
    try {
      await action()
      await client.invalidateQueries({ queryKey: forwardingKey })
    } catch (failure) {
      if (needsStepUp(failure)) setRetry(() => action)
      else setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  return (
    <section id="automate" aria-labelledby="settings-automate" className="flex scroll-mt-20 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="settings-automate" className="text-lg font-semibold">
          {t('forwarding.title')}
        </h2>
        <p className="text-sm text-muted-foreground">{t('forwarding.lead')}</p>
      </div>
      {forwarding.error ? (
        <LoadError what={t('forwarding.what')} error={forwarding.error} onRetry={() => void forwarding.refetch()} />
      ) : forwarding.data ? (
        <Body data={forwarding.data} run={run} />
      ) : null}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {retry && (
        <StepUpSheet
          email={email}
          onClose={() => setRetry(null)}
          onVerified={() => {
            const action = retry
            setRetry(null)
            void client.invalidateQueries({ queryKey: ['auth', 'me'] })
            void run(action)
          }}
        />
      )}
    </section>
  )
}

function Body({ data, run }: { data: Forwarding; run: (action: Action) => Promise<void> }) {
  return (
    <>
      <AddressPanel data={data} run={run} />
      {data.confirmation && <ConfirmationPanel confirmation={data.confirmation} run={run} />}
      <ForwardingInbox data={data} />
      {data.address && <PasswordsPanel data={data} run={run} />}
    </>
  )
}

function AddressPanel({ data, run }: { data: Forwarding; run: (action: Action) => Promise<void> }) {
  const [copied, setCopied] = useState(false)
  const id = useId()

  async function copy(address: string) {
    try {
      await navigator.clipboard.writeText(address)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <h3 id={id} className={PANEL_TITLE}>
        {t('forwarding.address.label')}
      </h3>
      {data.address ? (
        <>
          <p aria-labelledby={id} data-forwarding-address className="break-all font-mono text-[15px]">
            {data.address}
          </p>
          <p className="text-[13px] text-muted-foreground">{t('forwarding.address.private')}</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="outline" className="h-11 px-4" onClick={() => void copy(data.address ?? '')}>
              <Copy size={16} aria-hidden="true" />
              {copied ? t('forwarding.address.copied') : t('forwarding.address.copy')}
            </Button>
            <Button variant="outline" className="h-11 px-4" onClick={() => void run(async () => void (await rotateAddress()))}>
              <RefreshCw size={16} aria-hidden="true" />
              {t('forwarding.address.rotate')}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t('forwarding.address.rotateHint')}</p>
          <Link to="/settings/forwarding-guide" className={cn('min-h-11 text-sm font-semibold text-primary underline-offset-4 hover:underline', FOCUS)}>
            {t('forwarding.guide.link')}
          </Link>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-2">{t('forwarding.address.none')}</p>
          <Button
            className="h-11 self-start px-5"
            onClick={() => void run(async () => void (await (data.created ? rotateAddress() : createAddress())))}
          >
            {t('forwarding.address.create')}
          </Button>
        </>
      )}
    </div>
  )
}

function ConfirmationPanel({
  confirmation,
  run,
}: {
  confirmation: Confirmation
  run: (action: Action) => Promise<void>
}) {
  const id = useId()
  const link = safeGmailLink(confirmation.link)
  return (
    <section aria-labelledby={id} className={cn(PANEL, 'flex flex-col gap-3 border-primary/40 px-5 py-4')}>
      <h3 id={id} className={PANEL_TITLE}>
        {t('forwarding.confirmation.title')}
      </h3>
      <p className="text-sm text-ink-2">{t('forwarding.confirmation.lead')}</p>
      {confirmation.requester && (
        <p data-confirmation-requester className="break-all text-sm font-medium">
          {t('forwarding.confirmation.requester', { email: confirmation.requester })}
        </p>
      )}
      {confirmation.code && (
        <p data-confirmation-code className="font-mono text-xl font-semibold tracking-wider">
          {t('forwarding.confirmation.code', { code: confirmation.code })}
        </p>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        {link && (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className={cn('inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-semibold text-primary hover:bg-muted', FOCUS)}
          >
            {t('forwarding.confirmation.link')}
          </a>
        )}
        <Button variant="ghost" className="h-11 px-4" onClick={() => void run(dismissConfirmation)}>
          {t('forwarding.confirmation.dismiss')}
        </Button>
      </div>
    </section>
  )
}

function PasswordsPanel({ data, run }: { data: Forwarding; run: (action: Action) => Promise<void> }) {
  const [editing, setEditing] = useState<SupportedBank | null>(null)
  const id = useId()
  return (
    <section aria-labelledby={id} className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <h3 id={id} className={PANEL_TITLE}>
        {t('forwarding.passwords.title')}
      </h3>
      <p className="text-sm text-ink-2">{t('forwarding.passwords.lead')}</p>
      <ul className="flex flex-col">
        {SUPPORTED_BANKS.map((bank) => (
          <li key={bank} className="flex flex-col gap-2 border-b border-border py-2 last:border-b-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-24 text-sm font-medium">{bankName(bank)}</span>
              <Badge variant={data.passwords[bank] ? 'secondary' : 'outline'}>
                {data.passwords[bank] ? t('forwarding.passwords.stored') : t('forwarding.passwords.none')}
              </Badge>
              <span className="flex-1" />
              {data.passwords[bank] ? (
                <Button variant="ghost" className="h-11 px-3" onClick={() => void run(() => forgetPassword(bank))}>
                  {t('forwarding.passwords.forget')}
                </Button>
              ) : (
                editing !== bank && (
                  <Button variant="ghost" className="h-11 px-3" onClick={() => setEditing(bank)}>
                    {t('forwarding.passwords.store')}
                  </Button>
                )
              )}
            </div>
            {editing === bank && (
              <PasswordForm
                bank={bank}
                onCancel={() => setEditing(null)}
                onSave={(password) =>
                  run(async () => {
                    await storePassword(bank, password)
                    setEditing(null)
                  })
                }
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

interface PasswordFormProps {
  bank: SupportedBank
  onSave: (password: string) => Promise<void>
  onCancel: () => void
}

/** The password lives only in this field while typing; it is cleared once sent. */
function PasswordForm({ bank, onSave, onCancel }: PasswordFormProps) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const id = useId()

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!password) return
    setBusy(true)
    try {
      await onSave(password)
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={submit}>
      <label htmlFor={id} className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm font-medium">
        {t('forwarding.passwords.field', { bank: bankName(bank) })}
        <Input
          id={id}
          type="password"
          autoComplete="off"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="h-11"
        />
      </label>
      <Button type="submit" className="h-11 px-4" disabled={busy || !password}>
        {t('forwarding.passwords.save')}
      </Button>
      <Button type="button" variant="ghost" className="h-11 px-3" onClick={onCancel}>
        {t('forwarding.passwords.cancel')}
      </Button>
    </form>
  )
}
