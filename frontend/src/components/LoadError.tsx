import { Button } from '@/components/ui/button'
import { t } from '@/i18n'

interface LoadErrorProps {
  what: string
  error: Error
  onRetry: () => void
}

/** Inline load error, without alarm, with a button to retry. */
export function LoadError({ what, error, onRetry }: LoadErrorProps) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-card px-6 py-5"
    >
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold">{t('common.loadError', { what })}</p>
        <p className="text-[13px] text-muted-foreground">{error.message}</p>
      </div>
      <Button variant="outline" className="h-11 px-4" onClick={onRetry}>
        {t('common.retry')}
      </Button>
    </div>
  )
}
