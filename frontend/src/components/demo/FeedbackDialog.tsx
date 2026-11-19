import { useState } from 'react'
import { useLocation } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { LOCALE, t } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { OPINION_MAX, opinionBody, opinionProblem, refFrom, sendOpinion, useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

// The `?ref=` of the URL the visitor came in with (saved with each piece of feedback).
const ENTRY_REF = typeof window === 'undefined' ? null : refFrom(window.location.search)

/** "Feedback": text and an optional email; page, width, version, date and `ref` go on their own. */
export function FeedbackDialog({ onClose }: { onClose: () => void }) {
  const mode = useMode()
  const location = useLocation()
  const [text, setText] = useState('')
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    const problem = opinionProblem(text, email)
    if (problem) {
      setError(problem)
      return
    }
    setState('sending')
    setError(null)
    const context = {
      path: location.pathname,
      width: window.innerWidth,
      version: mode.version,
      ref: ENTRY_REF,
    }
    try {
      await sendOpinion(opinionBody(text, email, context))
      setState('sent')
    } catch (failure) {
      setState('idle')
      setError((failure as Error).message)
    }
  }

  if (state === 'sent') {
    return (
      <Modal title={t('demo.feedback.thanks')} onClose={onClose}>
        <p role="status" className="text-sm">
          {t('demo.feedback.received')}
        </p>
        <Button className="h-11 self-end px-4" onClick={onClose}>
          {t('demo.feedback.close')}
        </Button>
      </Modal>
    )
  }
  return (
    <Modal title={t('demo.feedback.title')} onClose={onClose}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          {t('demo.feedback.question')}
          <textarea
            value={text}
            maxLength={OPINION_MAX}
            rows={5}
            onChange={(event) => setText(event.target.value)}
            className={cn(
              'w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base font-normal md:text-sm',
              FOCUS,
            )}
          />
        </label>
        <p className="-mt-2 text-right text-xs text-muted-foreground">
          {t('demo.feedback.counter', {
            length: text.length.toLocaleString(LOCALE),
            max: OPINION_MAX.toLocaleString(LOCALE),
          })}
        </p>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          {t('demo.feedback.email')}
          <Input
            type="email"
            value={email}
            autoComplete="email"
            onChange={(event) => setEmail(event.target.value)}
            className="h-11"
          />
        </label>
        <p className="text-xs text-muted-foreground">
          {t('demo.feedback.context')}
        </p>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="h-11 self-end px-4" disabled={state === 'sending'}>
          {state === 'sending' ? t('demo.feedback.sending') : t('demo.feedback.send')}
        </Button>
      </form>
    </Modal>
  )
}
