import { type FormEvent, useId, useState } from 'react'
import { StepUpSheet } from '@/components/hosted/StepUpSheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { t } from '@/i18n'
import { SIGNED_OUT_EVENT } from '@/lib/api'
import { confirmsEmail, deleteAccount, needsStepUp, rememberAccountDeleted } from '@/lib/hosted'

type Step = 'idle' | 'confirm' | 'stepUp'

const LOSSES = [
  'auth.delete.lossData',
  'auth.delete.lossNow',
  'auth.delete.lossBackups',
  'auth.delete.lossGmail',
  'auth.delete.lossSessions',
] as const

/** Hosted mode's danger zone: deleting the account (`DELETE /api/account`, immediate). A dialog
 * says what is lost and asks for the account's email; the button works only once it matches.
 * When the server wants a fresh verification the step-up sheet comes first, then the deletion is
 * retried. Afterwards the app goes back to the signed-out page with a short notice. */
export function DeleteAccount({ email }: { email: string }) {
  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState<string | null>(null)

  async function remove() {
    setError(null)
    try {
      await deleteAccount()
    } catch (failure) {
      if (needsStepUp(failure)) {
        setStep('stepUp')
        return
      }
      setError(failure instanceof Error ? failure.message : String(failure))
      setStep('confirm')
      return
    }
    rememberAccountDeleted()
    window.history.replaceState(null, '', '/')
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
  }

  return (
    <section
      aria-labelledby="settings-delete"
      className="mt-4 flex flex-col gap-3 rounded-2xl border border-destructive/40 p-4"
    >
      <h2 id="settings-delete" className="text-lg font-semibold text-destructive">
        {t('auth.delete.title')}
      </h2>
      <p className="text-sm text-ink-2">{t('auth.delete.lead')}</p>
      <Button
        variant="destructive"
        className="h-11 self-start px-4"
        onClick={() => {
          setError(null)
          setStep('confirm')
        }}
      >
        {t('auth.delete.open')}
      </Button>
      {step === 'confirm' && (
        <ConfirmDialog
          email={email}
          error={error}
          onConfirm={remove}
          onClose={() => setStep('idle')}
        />
      )}
      {step === 'stepUp' && (
        <StepUpSheet
          email={email}
          onClose={() => setStep('idle')}
          onVerified={() => void remove()}
        />
      )}
    </section>
  )
}

interface ConfirmDialogProps {
  email: string
  error: string | null
  onConfirm: () => Promise<void>
  onClose: () => void
}

function ConfirmDialog({ email, error, onConfirm, onClose }: ConfirmDialogProps) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const id = useId()
  const matches = confirmsEmail(typed, email)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!matches || busy) return
    setBusy(true)
    try {
      await onConfirm()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={t('auth.delete.dialogTitle')} onClose={onClose}>
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
        <div className="flex flex-col gap-2 text-sm text-ink-2">
          <p>{t('auth.delete.loses')}</p>
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {LOSSES.map((key) => (
              <li key={key}>{t(key)}</li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor={`${id}-email`} className="text-sm font-medium">
            {t('auth.delete.typeEmail', { email })}
          </label>
          <Input
            id={`${id}-email`}
            type="email"
            inputMode="email"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            className="h-11"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex flex-col gap-2 sm:flex-row-reverse">
          <Button type="submit" variant="destructive" className="h-11 px-4" disabled={!matches || busy}>
            {busy ? t('auth.delete.deleting') : t('auth.delete.confirm')}
          </Button>
          <Button type="button" variant="ghost" className="h-11 px-4" onClick={onClose}>
            {t('auth.delete.cancel')}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
