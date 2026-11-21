import { t } from '@/i18n'

interface CardErrorProps {
  /** What did not load, as a catalog phrase (e.g. the budget). */
  what: string
  error: Error
  onRetry: () => void
}

/** A card's part that did not load: one line with the reason and «Retry» (above the card's
 * link, so the tap retries instead of navigating). */
export function CardError({ what, error, onRetry }: CardErrorProps) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <p className="min-w-0 text-[13px] text-ink-2">
        {t('common.loadError', { what })}{' '}
        <span className="text-muted-foreground">{error.message}</span>
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="relative z-[2] inline-flex min-h-11 items-center rounded-lg px-2 text-[13px] font-semibold text-primary outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {t('common.retry')}
      </button>
    </div>
  )
}
