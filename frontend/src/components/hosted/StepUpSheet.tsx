import { type FormEvent, useId, useState } from 'react'
import { CodeField } from '@/components/hosted/CodeField'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { requestStepUp, validCode, verifyStepUp } from '@/lib/hosted'

interface StepUpSheetProps {
  email: string
  onVerified: () => void
  onClose: () => void
}

/** A fresh verification before a sensitive action: a new code by email, typed here. The code is
 * sent only when asked (one tap), never on its own. */
export function StepUpSheet({ email, onVerified, onClose }: StepUpSheetProps) {
  const [sent, setSent] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const id = useId()

  async function run(work: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!validCode(code)) {
      setError(t('auth.signIn.badCode'))
      return
    }
    void run(async () => {
      await verifyStepUp(code)
      onVerified()
    })
  }

  return (
    <BottomSheet title={t('auth.stepUp.title')} onClose={onClose}>
      <p id={`${id}-lead`} className="text-sm text-ink-2">
        {t('auth.stepUp.lead', { email })}
      </p>
      {!sent ? (
        <Button
          className="h-11"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await requestStepUp()
              setSent(true)
            })
          }
        >
          {t('auth.stepUp.send')}
        </Button>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={submit} noValidate>
          <CodeField
            id={`${id}-code`}
            value={code}
            onChange={setCode}
            invalid={error !== null}
            describedBy={`${id}-lead`}
          />
          <Button type="submit" className="h-11" disabled={busy}>
            {t('auth.stepUp.confirm')}
          </Button>
        </form>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button variant="ghost" className="h-11" onClick={onClose}>
        {t('auth.stepUp.cancel')}
      </Button>
    </BottomSheet>
  )
}
