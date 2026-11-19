import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { hintText } from '@/lib/log'
import { useHistory } from '@/lib/logQueries'
import { cn } from '@/lib/utils'
import { LogEntryRow } from './LogEntryRow'

interface HistorySectionProps {
  fingerprint: string
}

/** The history in a transaction's detail: its change-log entries and, when its merchant already
 * got the same category by hand on others, the hint ("the other 2 times…"). */
export function HistorySection({ fingerprint }: HistorySectionProps) {
  const history = useHistory(fingerprint)
  if (history.isPending || history.isError) return null
  const { items, rule_hint: hint } = history.data
  return (
    <section aria-labelledby={`${fingerprint}-history`} className="flex min-w-0 flex-col gap-1">
      {hint && (
        <p className="mb-2 rounded-[10px] border border-dashed border-primary/40 px-3 py-2.5 text-[13px] text-ink-2">
          {hintText(hint)}
        </p>
      )}
      <h3
        id={`${fingerprint}-history`}
        className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase"
      >
        {t('log.history.title')}
      </h3>
      {items.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('log.history.none')}</p>
      ) : (
        <ul className="flex flex-col">
          {items.map((entry) => (
            <LogEntryRow key={entry.id} entry={entry} showLink={false} />
          ))}
        </ul>
      )}
      <Link
        to="/log"
        className={cn(
          '-mx-2 flex min-h-11 items-center self-start rounded-md px-2 text-[13px] font-semibold text-primary no-underline hover:bg-muted/60',
          FOCUS,
        )}
      >
        {t('log.history.viewLog')}
      </Link>
    </section>
  )
}
