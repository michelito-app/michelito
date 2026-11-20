import { useId, useState } from 'react'
import { PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { LOCALE, t } from '@/i18n'
import { type Job, type SharedFile, claimShare, discardShare } from '@/lib/onboarding'
import { cn } from '@/lib/utils'

interface SharePromptProps {
  token: string
  files: SharedFile[]
  onImported: (job: Job) => void
  onDone: () => void
}

const KB = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 })

/** Files shared to the app from the phone: never imported on their own. Their names and sizes
 * are shown and nothing happens until "Import" (or "Discard"). */
export function SharePrompt({ token, files, onImported, onDone }: SharePromptProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const id = useId()

  async function act(importing: boolean) {
    setBusy(true)
    setError(null)
    try {
      if (importing) onImported(await claimShare(token))
      else await discardShare(token)
      onDone()
    } catch (failure) {
      setError((failure as Error).message)
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby={id} className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <h2 id={id} className="text-[17px] font-[650] tracking-tight">
        {t('onboarding.share.title', { count: files.length })}
      </h2>
      <p className="text-sm text-ink-2">{t('onboarding.share.lead')}</p>
      <ul className="flex flex-col gap-1">
        {files.map((file, index) => (
          <li key={index} className="flex justify-between gap-3 text-sm">
            <span className="min-w-0 truncate font-medium">{file.name}</span>
            <span className="shrink-0 text-muted-foreground">
              {t('onboarding.share.size', { size: KB.format(Math.max(1, file.size / 1024)) })}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button className="h-11 px-5" disabled={busy} onClick={() => void act(true)}>
          {t('onboarding.share.import')}
        </Button>
        <Button variant="outline" className="h-11 px-5" disabled={busy} onClick={() => void act(false)}>
          {t('onboarding.share.discard')}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </section>
  )
}
