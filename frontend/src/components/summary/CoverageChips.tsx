import { t } from '@/i18n'
import type { Coverage } from '@/lib/api'
import { coverageText } from '@/lib/summary'
import { cn } from '@/lib/utils'

/** One indicator per account: "complete" or through which day its data reaches. */
export function CoverageChips({ coverage }: { coverage: Coverage[] }) {
  if (coverage.length === 0) return null
  return (
    <ul aria-label={t('summary.coverage.label')} className="flex flex-wrap gap-2">
      {coverage.map((c) => (
        <li
          key={c.key}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-[13px] text-ink-2"
        >
          <span
            aria-hidden="true"
            className={cn('size-2 rounded-full', c.complete ? 'bg-primary' : 'bg-up')}
          />
          {c.label} · {coverageText(c)}
        </li>
      ))}
    </ul>
  )
}
