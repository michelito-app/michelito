import { type FormEvent, useId, useState } from 'react'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import {
  type Job,
  SUPPORTED_BANKS,
  type SupportedBank,
  bankName,
  lockedFiles,
  tryPassword,
} from '@/lib/onboarding'
import { cn } from '@/lib/utils'

interface PasswordPromptProps {
  job: Job
  onTried: (job: Job) => void
}

/** The PDF password, asked once per bank and tried on every locked file of the upload. It only
 * lives in this form while typing: it is sent in the POST body and cleared right after. */
export function PasswordPrompt({ job, onTried }: PasswordPromptProps) {
  const [bank, setBank] = useState<SupportedBank>(
    (SUPPORTED_BANKS.find((b) => job.misses.includes(b)) ?? SUPPORTED_BANKS[0]) as SupportedBank,
  )
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  const left = lockedFiles(job).length

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!password) return
    setBusy(true)
    setError(null)
    try {
      const tried = await tryPassword(job.id, bank, password)
      onTried(tried)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <section
      aria-labelledby={`${id}-title`}
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <h2 id={`${id}-title`} className="text-[17px] font-[650] tracking-tight">
        {t('onboarding.password.title')}
      </h2>
      <p className="text-sm text-ink-2">{t('onboarding.password.lead')}</p>
      <p className="text-[13px] text-muted-foreground">
        {t('onboarding.password.left', { count: left })}
      </p>
      {job.last_try && job.last_try.opened > 0 && (
        <p role="status" className="text-sm text-down">
          {t('onboarding.password.tried', {
            count: job.last_try.opened,
            bank: bankName(job.last_try.bank),
          })}
        </p>
      )}
      {job.misses.map((missed) => (
        <p key={missed} role="alert" className="text-sm text-destructive">
          {t('onboarding.password.wrong', { bank: bankName(missed) })}
        </p>
      ))}
      <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
        <label htmlFor={`${id}-bank`} className="flex flex-col gap-1 text-sm font-medium">
          {t('onboarding.password.bank')}
          <select
            id={`${id}-bank`}
            value={bank}
            onChange={(event) => setBank(event.target.value as SupportedBank)}
            className={cn('h-11 rounded-lg border border-input bg-card px-2 text-sm', FOCUS)}
          >
            {SUPPORTED_BANKS.map((key) => (
              <option key={key} value={key}>
                {bankName(key)}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={`${id}-password`} className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm font-medium">
          {t('onboarding.password.field')}
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
          {busy ? t('onboarding.password.trying') : t('onboarding.password.submit')}
        </Button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </section>
  )
}
