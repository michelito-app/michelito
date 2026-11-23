import { type FormEvent, useCallback, useEffect, useId, useState } from 'react'
import { CodeField } from '@/components/hosted/CodeField'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import { type ModeInfo } from '@/lib/demo'
import {
  accountDeleted,
  cooldownLeft,
  forgetAccountDeleted,
  peekLink,
  requestCode,
  validCode,
  validEmail,
  verifyCode,
  verifyLink,
} from '@/lib/hosted'

type Step = 'landing' | 'email' | 'code' | 'link'

interface SignedOutProps {
  mode: ModeInfo
  /** A desktop link's token, already taken out of the address by the mode gate. */
  link: string | null
  onSignedIn: () => void
}

const PAGE = 'mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-6 px-4 py-10'
const BIG = 'h-12 w-full text-base'

/** Hosted mode without a session: the landing (title, the demo, Enter) and the sign-in by
 * email code. A desktop link from the email is never used on its own: the page first asks
 * whether to enter as its (masked) email, so a link someone else planted does nothing. */
export function SignedOut({ mode, link, onSignedIn }: SignedOutProps) {
  const [step, setStep] = useState<Step>(link ? 'link' : 'landing')
  const [email, setEmail] = useState('')
  const [linkError, setLinkError] = useState<string | null>(null)

  const linkFailed = useCallback(() => {
    setLinkError(t('auth.signIn.linkFailed'))
    setStep('email')
  }, [])

  if (step === 'link' && link) {
    return (
      <LinkStep
        token={link}
        onSignedIn={onSignedIn}
        onFailed={linkFailed}
        onCancel={() => setStep('landing')}
      />
    )
  }
  if (step === 'landing') return <Landing mode={mode} onEnter={() => setStep('email')} />
  if (step === 'email') {
    return (
      <EmailStep
        initial={email}
        notice={linkError}
        onBack={() => setStep('landing')}
        onSent={(sent) => {
          setEmail(sent)
          setLinkError(null)
          setStep('code')
        }}
      />
    )
  }
  return <CodeStep email={email} onOther={() => setStep('email')} onSignedIn={onSignedIn} />
}

interface LinkStepProps {
  token: string
  onSignedIn: () => void
  onFailed: () => void
  onCancel: () => void
}

/** "Enter as a•••@example.com?": looks the link up without using it, and uses it only on a tap. */
function LinkStep({ token, onSignedIn, onFailed, onCancel }: LinkStepProps) {
  const [masked, setMasked] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    peekLink(token)
      .then((found) => {
        if (alive) setMasked(found)
      })
      .catch(() => {
        if (alive) onFailed()
      })
    return () => {
      alive = false
    }
  }, [token, onFailed])

  async function enter() {
    setBusy(true)
    try {
      await verifyLink(token)
      onSignedIn()
    } catch {
      onFailed()
    }
  }

  if (masked === null) {
    return (
      <p role="status" className="p-10 text-sm text-muted-foreground">
        {t('demo.gate.loading')}
      </p>
    )
  }
  return (
    <main className={PAGE}>
      <h1 className="text-2xl font-bold tracking-tight">
        {t('auth.link.confirm', { email: masked })}
      </h1>
      <p className="text-sm text-ink-2">{t('auth.link.lead')}</p>
      <Button className={BIG} disabled={busy} onClick={() => void enter()}>
        {t('auth.link.enter')}
      </Button>
      <Button variant="ghost" className="h-11" onClick={onCancel}>
        {t('auth.link.cancel')}
      </Button>
    </main>
  )
}

function Landing({ mode, onEnter }: { mode: ModeInfo; onEnter: () => void }) {
  // Read during render, taken away in an effect: StrictMode's second render still sees it.
  const [deleted] = useState(() => accountDeleted())
  useEffect(() => {
    if (deleted) forgetAccountDeleted()
  }, [deleted])
  return (
    <main className={PAGE}>
      {deleted && (
        <p role="status" className="rounded-lg border border-border bg-muted px-4 py-3 text-sm">
          {t('auth.delete.done')}
        </p>
      )}
      <h1 className="text-3xl font-bold tracking-tight">{t('auth.landing.title')}</h1>
      <p className="text-base text-ink-2">{t('auth.landing.lead')}</p>
      <div className="flex flex-col gap-3">
        <Button className={BIG} onClick={onEnter}>
          {t('auth.landing.enter')}
        </Button>
        {mode.demo_url && (
          <a
            href={mode.demo_url}
            className="flex h-12 items-center justify-center rounded-lg border border-border text-base font-medium no-underline"
          >
            {t('auth.landing.demo')}
          </a>
        )}
      </div>
      <p className="text-sm text-muted-foreground">{t('auth.landing.invite')}</p>
      <a href="/privacy" className="inline-flex min-h-11 items-center self-start text-sm text-muted-foreground underline underline-offset-4">
        {t('auth.landing.privacy')}
      </a>
    </main>
  )
}

interface EmailStepProps {
  initial: string
  notice: string | null
  onBack: () => void
  onSent: (email: string) => void
}

function EmailStep({ initial, notice, onBack, onSent }: EmailStepProps) {
  const [email, setEmail] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const id = useId()

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!validEmail(email)) {
      setError(t('auth.signIn.badEmail'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await requestCode(email)
      onSent(email.trim())
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className={PAGE}>
      <h1 className="text-2xl font-bold tracking-tight">{t('auth.signIn.title')}</h1>
      {notice && (
        <p role="alert" className="text-sm text-destructive">
          {notice}
        </p>
      )}
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-email`} className="text-sm font-medium">
            {t('auth.signIn.email')}
          </label>
          <Input
            id={`${id}-email`}
            type="email"
            inputMode="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={error ? true : undefined}
            className="h-12 text-base md:text-base"
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className={BIG} disabled={busy}>
          {busy ? t('auth.signIn.sending') : t('auth.signIn.sendCode')}
        </Button>
        <Button type="button" variant="ghost" className="h-11" onClick={onBack}>
          {t('auth.signIn.back')}
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">{t('auth.signIn.inviteOnly')}</p>
    </main>
  )
}

interface CodeStepProps {
  email: string
  onOther: () => void
  onSignedIn: () => void
}

function CodeStep({ email, onOther, onSignedIn }: CodeStepProps) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sentAt, setSentAt] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  const id = useId()
  const left = cooldownLeft(sentAt, now)

  useEffect(() => {
    if (left === 0) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [left])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!validCode(code)) {
      setError(t('auth.signIn.badCode'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await verifyCode(email, code)
      onSignedIn()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
      setBusy(false)
    }
  }

  async function resend() {
    setError(null)
    try {
      await requestCode(email)
      setSentAt(Date.now())
      setNow(Date.now())
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  return (
    <main className={PAGE}>
      <h1 className="text-2xl font-bold tracking-tight">{t('auth.signIn.title')}</h1>
      <p id={`${id}-sent`} className="text-base text-ink-2">
        {t('auth.signIn.sent', { email })}
      </p>
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        <CodeField
          id={`${id}-code`}
          value={code}
          onChange={setCode}
          invalid={error !== null}
          describedBy={`${id}-sent`}
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className={BIG} disabled={busy}>
          {busy ? t('auth.signIn.verifying') : t('auth.signIn.verify')}
        </Button>
      </form>
      <div className="flex flex-col gap-2">
        <Button variant="outline" className="h-11" disabled={left > 0} onClick={resend}>
          {left > 0 ? t('auth.signIn.resendIn', { seconds: left }) : t('auth.signIn.resend')}
        </Button>
        <Button variant="ghost" className="h-11" onClick={onOther}>
          {t('auth.signIn.otherEmail')}
        </Button>
      </div>
    </main>
  )
}
