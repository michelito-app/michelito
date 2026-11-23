import { useQueryClient } from '@tanstack/react-query'
import { Copy, Download, KeyRound } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  type ExtensionCode,
  type ExtensionStatus,
  DOWNLOAD_PATH,
  codeExpiry,
  extensionKey,
  linkedLine,
  makeCode,
  revoke,
  useExtension,
} from '@/lib/extension'
import { cn } from '@/lib/utils'

const SECTION_ID = 'extension'
const LINK = cn('inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-primary underline-offset-4 hover:underline', FOCUS)
const STEPS = ['extension.step1', 'extension.step2', 'extension.step3', 'extension.step4', 'extension.step5'] as const

interface Notice {
  text: string
  good: boolean
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure)
}

/** Settings → Amazon extension (hosted): download it, make the one-time code it is linked with,
 * see whether a Chrome is linked and revoke it. The extension's token never comes here. */
export function ExtensionSettings() {
  const extension = useExtension()
  const [notice, setNotice] = useState<Notice | null>(null)

  if (extension.error) {
    return (
      <Section>
        <LoadError what={t('extension.what')} error={extension.error} onRetry={() => void extension.refetch()} />
      </Section>
    )
  }
  if (!extension.data) return null
  return (
    <Section>
      {notice && (
        <p
          role={notice.good ? 'status' : 'alert'}
          className={cn('rounded-xl px-4 py-3 text-sm', notice.good ? 'bg-muted text-ink-2' : 'bg-destructive/10 text-destructive')}
        >
          {notice.text}
        </p>
      )}
      <LinkPanel status={extension.data} onNotice={setNotice} />
      <Install />
    </Section>
  )
}

function Section({ children }: { children: ReactNode }) {
  return (
    <section id={SECTION_ID} aria-labelledby="settings-extension" className="flex scroll-mt-20 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="settings-extension" className="text-lg font-semibold">
          {t('extension.title')}
        </h2>
        <p className="text-sm text-muted-foreground">{t('extension.lead')}</p>
      </div>
      {children}
      <p className="text-xs text-muted-foreground">{t('extension.reads')}</p>
      <a href="/privacy" className={cn(LINK, 'self-start')}>
        {t('extension.privacy')}
      </a>
    </section>
  )
}

interface LinkPanelProps {
  status: ExtensionStatus
  onNotice: (notice: Notice | null) => void
}

function LinkPanel({ status, onNotice }: LinkPanelProps) {
  const client = useQueryClient()
  const [code, setCode] = useState<ExtensionCode | null>(null)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  async function act(action: () => Promise<void>) {
    setBusy(true)
    onNotice(null)
    try {
      await action()
    } catch (failure) {
      onNotice({ text: message(failure), good: false })
    } finally {
      setBusy(false)
      await client.invalidateQueries({ queryKey: extensionKey })
    }
  }

  const newCode = () => act(async () => setCode(await makeCode()))
  const cut = () =>
    act(async () => {
      await revoke()
      setAsking(false)
      setCode(null)
      onNotice({ text: t('extension.revoked'), good: true })
    })

  return (
    <div className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <div className="flex flex-col gap-0.5">
        <h3 className={PANEL_TITLE}>{status.linked ? t('extension.linkedTitle') : t('extension.notLinked')}</h3>
        {status.linked && (
          <p data-testid="extension-linked" className="text-sm text-ink-2">
            {linkedLine(status)}
          </p>
        )}
      </div>
      {code && <CodeBox code={code} />}
      {asking ? (
        <div role="alertdialog" aria-label={t('extension.revoke')} className="flex flex-col gap-2 rounded-xl bg-muted px-3 py-3">
          <p className="text-sm text-ink-2">{t('extension.revokeLead')}</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="destructive" className="h-11 px-4" disabled={busy} onClick={() => void cut()}>
              {t('extension.revokeYes')}
            </Button>
            <Button variant="ghost" className="h-11 px-4" onClick={() => setAsking(false)}>
              {t('extension.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button className="h-11 px-5" disabled={busy} onClick={() => void newCode()}>
            <KeyRound size={16} aria-hidden="true" />
            {code ? t('extension.makeAnother') : t('extension.makeCode')}
          </Button>
          {status.linked && (
            <Button variant="ghost" className="h-11 px-4" disabled={busy} onClick={() => setAsking(true)}>
              {t('extension.revoke')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function CodeBox({ code }: { code: ExtensionCode }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(code.code)
      setCopied(true)
    } catch {
      setCopied(false) // the code stays on screen to type by hand
    }
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-xl bg-secondary px-4 py-3">
      <span id="extension-code-label" className="text-xs font-semibold text-secondary-foreground">
        {t('extension.codeLabel')}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <output
          aria-labelledby="extension-code-label"
          data-testid="extension-code"
          className="font-mono text-xl font-semibold tracking-[0.12em] select-all"
        >
          {code.code}
        </output>
        <Button variant="outline" className="h-11 px-3" onClick={() => void copy()}>
          <Copy size={16} aria-hidden="true" />
          {copied ? t('extension.copied') : t('extension.copy')}
        </Button>
      </div>
      <p className="text-xs text-secondary-foreground">
        {codeExpiry(code.expires_at)} {t('extension.codeHint')}
      </p>
    </div>
  )
}

function Install() {
  return (
    <div className="flex flex-col gap-2">
      <a href={DOWNLOAD_PATH} download className={cn(LINK, 'self-start')}>
        <Download size={16} aria-hidden="true" />
        {t('extension.download')}
      </a>
      <h3 className="text-sm font-semibold">{t('extension.stepsTitle')}</h3>
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-ink-2">
        {STEPS.map((step) => (
          <li key={step}>{t(step)}</li>
        ))}
      </ol>
    </div>
  )
}
