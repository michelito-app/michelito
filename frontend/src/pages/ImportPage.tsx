import { useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { UploadFlow } from '@/components/onboarding/UploadFlow'
import { PANEL, WIDGET_ACTION } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { type SampleResult, importSample, isDemo, isHosted, useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

/** Import statements. In the demo the file input is disabled (real statements are never
 * uploaded) and a sample statement is tried instead; locally statements are imported with
 * `michelito import`, and uploading from here is left for later. */
export function ImportPage() {
  const mode = useMode()
  if (isHosted(mode)) return <HostedImport demoUrl={mode.demo_url} />
  return <LocalImport />
}

/** Hosted mode after the gate: the same upload and processing screen as the gate. */
function HostedImport({ demoUrl }: { demoUrl?: string }) {
  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
        {t('onboarding.upload.title')}
      </h1>
      <p className="text-sm text-ink-2">{t('onboarding.upload.lead')}</p>
      <UploadFlow demoUrl={demoUrl} />
    </div>
  )
}

function LocalImport() {
  const mode = useMode()
  const demo = isDemo(mode)
  const hint = useId()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">{t('import.title')}</h1>
      <section aria-label={t('import.upload.label')} className={cn(PANEL, 'flex flex-col gap-3 px-6 py-5')}>
        <label className="flex flex-col gap-2 text-sm font-semibold">
          {t('import.upload.file')}
          <input
            type="file"
            accept="application/pdf"
            disabled
            aria-describedby={hint}
            className="text-sm font-normal disabled:cursor-not-allowed disabled:opacity-60"
          />
        </label>
        <p id={hint} className="text-[13px] text-muted-foreground">
          {demo
            ? t('import.upload.demoHint')
            : t('import.upload.localHint')}
        </p>
      </section>
      {demo && <SampleSection />}
    </div>
  )
}

function SampleSection() {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<SampleResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const found = await importSample()
      setResult(found)
      await queryClient.invalidateQueries()
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-labelledby="sample-title"
      className={cn(PANEL, 'flex flex-col gap-3 px-6 py-5')}
    >
      <h2 id="sample-title" className="text-[17px] font-[650] tracking-tight">
        {t('import.sample.title')}
      </h2>
      <p className="text-sm text-ink-2">
        {t('import.sample.body')}
      </p>
      <Button className="h-11 self-start px-4" disabled={busy} onClick={() => void run()}>
        <FileUp size={16} aria-hidden="true" />
        {busy ? t('import.sample.importing') : t('import.sample.try')}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {result && <SampleOutcome result={result} />}
    </section>
  )
}

function SampleOutcome({ result }: { result: SampleResult }) {
  const first = result.months[0]
  const last = result.months[result.months.length - 1]
  return (
    <div role="status" className="flex flex-col gap-1 rounded-xl bg-muted/60 px-4 py-3 text-sm">
      <p className="font-semibold">
        {result.balanced
          ? t('import.outcome.balanced', { count: result.transactions })
          : t('import.outcome.rejected', {
              status: result.status,
              detail: result.detail ?? t('import.outcome.noDetail'),
            })}
      </p>
      <p className="text-ink-2">
        {t('import.outcome.period', {
          account: result.account,
          start: result.period_start,
          end: result.period_end,
        })}
      </p>
      {result.balanced && (
        <div className="flex flex-wrap gap-x-4">
          <Link to={`/?month=${first}`} className={WIDGET_ACTION}>
            {t('import.outcome.review')}
          </Link>
          <Link to={`/transactions?month=${last}`} className={WIDGET_ACTION}>
            {t('import.outcome.transactions')}
          </Link>
        </div>
      )}
    </div>
  )
}
