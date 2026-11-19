import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { Pending } from '@/lib/api'
import {
  EMPTY_TEXT,
  type Figure,
  isEmpty,
  netTone,
  type NetTone,
  pendingFigures,
  pendingHref,
} from '@/lib/pending'
import { usePending } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { PANEL_TITLE, ROW_DIVIDER, WIDGET, WIDGET_ACTION } from './styles'

const NET_CLASS: Record<NetTone, string> = {
  positive: 'text-down',
  negative: 'text-up',
  zero: 'text-foreground',
}

/** "Pending" widget: owed to you, you owe and net across all months (not only the chosen one), with
 * the same figures as the Pending screen, where it leads. */
export function PendingCard({ selection = null }: { selection?: Selection }) {
  const pending = usePending(selection)
  if (pending.isPending) return <Skeleton className="h-full min-h-[164px] rounded-2xl" />

  return (
    <section aria-labelledby="pending-title" className={WIDGET}>
      <div className="-my-2 flex items-center justify-between gap-3">
        <h2 id="pending-title" className={PANEL_TITLE}>
          {t('summary.pendingCard.title')}
        </h2>
        <Link to={pendingHref(selection)} className={WIDGET_ACTION}>
          {t('summary.pendingCard.link')}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </div>
      {pending.isError ? (
        <p role="alert" className="text-[13px] text-muted-foreground">
          {t('summary.pendingCard.loadError', { message: pending.error.message })}
        </p>
      ) : (
        <CardBody data={pending.data} />
      )}
    </section>
  )
}

function CardBody({ data }: { data: Pending }) {
  if (isEmpty(data)) return <p className="text-[13px] text-muted-foreground">{EMPTY_TEXT} ✓</p>
  const tone = netTone(data.net_dop_cents)
  return (
    <>
      <ul className="flex flex-col">
        {pendingFigures(data).map((figure) => (
          <FigureLine
            key={figure.key}
            figure={figure}
            className={figure.key === 'net' ? NET_CLASS[tone] : undefined}
          />
        ))}
      </ul>
      <p className="mt-auto text-xs text-muted-foreground">
        {t('summary.pendingCard.note')}
      </p>
    </>
  )
}

function FigureLine({ figure, className }: { figure: Figure; className?: string }) {
  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col py-1.5')}>
      <span className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] text-ink-2">{figure.label}</span>
        <strong
          data-testid={`pending-card-${figure.key}`}
          className={cn('text-[15px] font-bold whitespace-nowrap tabular-nums', className)}
        >
          {figure.value}
        </strong>
      </span>
      {figure.extra && (
        <span className="text-right text-xs text-muted-foreground">{figure.extra}</span>
      )}
    </li>
  )
}
