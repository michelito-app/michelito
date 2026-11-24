import { useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { type Connection, connectionLine, connectionsKey, connectorUrl, revokeConnection, useConnections } from '@/lib/connector'
import { cn } from '@/lib/utils'

const STEPS = ['connector.step1', 'connector.step2', 'connector.step3'] as const

/** Settings → Claude and other AIs (hosted): the address to paste in Claude, how to add it, and
 * the connected AIs with a way to disconnect each one. */
export function ConnectorSettings() {
  const connections = useConnections()
  const [notice, setNotice] = useState<{ text: string; good: boolean } | null>(null)
  return (
    <Section>
      <UrlBox />
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-ink-2">
        {STEPS.map((step) => (
          <li key={step}>{t(step)}</li>
        ))}
      </ol>
      {notice && (
        <p
          role={notice.good ? 'status' : 'alert'}
          className={cn('rounded-xl px-4 py-3 text-sm', notice.good ? 'bg-muted text-ink-2' : 'bg-destructive/10 text-destructive')}
        >
          {notice.text}
        </p>
      )}
      {connections.error ? (
        <LoadError what={t('connector.what')} error={connections.error} onRetry={() => void connections.refetch()} />
      ) : (
        connections.data && <ConnectionList items={connections.data} onNotice={setNotice} />
      )}
      <p className="text-xs text-muted-foreground">{t('connector.sees')}</p>
    </Section>
  )
}

function Section({ children }: { children: ReactNode }) {
  return (
    <section id="connector" aria-labelledby="settings-connector" className="flex scroll-mt-20 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="settings-connector" className="text-lg font-semibold">
          {t('connector.title')}
        </h2>
        <p className="text-sm text-muted-foreground">{t('connector.lead')}</p>
      </div>
      {children}
    </section>
  )
}

function UrlBox() {
  const [copied, setCopied] = useState(false)
  const url = connectorUrl()

  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      setCopied(false) // the address stays on screen to copy by hand
    }
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-xl bg-secondary px-4 py-3">
      <span id="connector-url-label" className="text-xs font-semibold text-secondary-foreground">
        {t('connector.urlLabel')}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <output
          aria-labelledby="connector-url-label"
          data-testid="connector-url"
          className="min-w-0 font-mono text-sm font-semibold break-all select-all"
        >
          {url}
        </output>
        <Button variant="outline" className="h-11 px-3" onClick={() => void copy()}>
          <Copy size={16} aria-hidden="true" />
          {copied ? t('connector.copied') : t('connector.copy')}
        </Button>
      </div>
    </div>
  )
}

interface ListProps {
  items: Connection[]
  onNotice: (notice: { text: string; good: boolean } | null) => void
}

function ConnectionList({ items, onNotice }: ListProps) {
  if (items.length === 0) {
    return <p className={cn(PANEL, 'px-5 py-4 text-sm text-ink-2')}>{t('connector.none')}</p>
  }
  return (
    <ul className={cn(PANEL, 'flex flex-col px-5')} data-testid="connector-connections">
      {items.map((item) => (
        <ConnectionRow key={item.id} item={item} onNotice={onNotice} />
      ))}
    </ul>
  )
}

function ConnectionRow({ item, onNotice }: { item: Connection; onNotice: ListProps['onNotice'] }) {
  const client = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  async function cut() {
    setBusy(true)
    onNotice(null)
    try {
      await revokeConnection(item.id)
      onNotice({ text: t('connector.revoked'), good: true })
    } catch (failure) {
      onNotice({ text: failure instanceof Error ? failure.message : String(failure), good: false })
    } finally {
      setBusy(false)
      setAsking(false)
      await client.invalidateQueries({ queryKey: connectionsKey })
    }
  }

  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-4')}>
      <div className="flex flex-col gap-0.5">
        <h3 className={PANEL_TITLE}>{item.client_name}</h3>
        <p className="text-sm text-ink-2">{connectionLine(item)}</p>
      </div>
      {asking ? (
        <div role="alertdialog" aria-label={t('connector.revoke')} className="flex flex-col gap-2 rounded-xl bg-muted px-3 py-3">
          <p className="text-sm text-ink-2">{t('connector.revokeLead')}</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="destructive" className="h-11 px-4" disabled={busy} onClick={() => void cut()}>
              {t('connector.revokeYes')}
            </Button>
            <Button variant="ghost" className="h-11 px-4" onClick={() => setAsking(false)}>
              {t('connector.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="ghost" className="h-11 self-start px-4" onClick={() => setAsking(true)}>
          {t('connector.revoke')}
        </Button>
      )}
    </li>
  )
}
