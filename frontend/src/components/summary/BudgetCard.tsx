import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { Skeleton } from '@/components/ui/skeleton'
import { hrefWithSelection, type Selection } from '@/lib/accountFilter'
import { BUDGET_PATH, missingText, overviewText } from '@/lib/budget'
import { useBudgetOverview } from '@/lib/budgetQueries'
import { formatDop } from '@/lib/money'
import { monthPhrase } from '@/lib/months'
import { cn } from '@/lib/utils'
import { PANEL, PANEL_TITLE, ROW_DIVIDER, WIDGET_ACTION } from './styles'

interface BudgetCardProps {
  month: string
  selection: Selection
}

/** Tarjeta compacta del Resumen: cuántas categorías pasaron su tope en el mes (con el exceso) y
 * los próximos gastos grandes: las reservas que vencen en los próximos 60 días. */
export function BudgetCard({ month, selection }: BudgetCardProps) {
  const overview = useBudgetOverview(month, selection)
  const href = hrefWithSelection(BUDGET_PATH, { mes: month }, selection)
  if (overview.isPending) return <Skeleton className="h-[120px] rounded-2xl" />
  return (
    <section
      aria-labelledby="budget-card-title"
      className={cn(PANEL, 'grid gap-4 px-5 py-4 md:grid-cols-2')}
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="-my-2 flex items-center justify-between gap-3">
          <h2 id="budget-card-title" className={PANEL_TITLE}>
            Presupuesto
          </h2>
          <Link to={href} className={WIDGET_ACTION}>
            Ver presupuesto
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
        {overview.isError ? (
          <p role="alert" className="text-[13px] text-muted-foreground">
            No se pudo cargar el presupuesto: {overview.error.message}
          </p>
        ) : !overview.data.active ? (
          <p className="text-[13px] text-muted-foreground">
            Sin activar: pon un tope por categoría en Presupuesto.
          </p>
        ) : (
          <p
            data-testid="budget-status"
            className={cn(
              'text-sm font-semibold',
              (overview.data.over_count ?? 0) > 0 ? 'text-up' : 'text-ink-2',
            )}
          >
            {overviewText(overview.data).replace(/RD\$ /g, 'RD$\u00a0')}
          </p>
        )}
        {overview.data && missingText(overview.data.missing) && (
          <p className="text-[13px] text-up-ink">{missingText(overview.data.missing)}</p>
        )}
      </div>
      <div
        className="flex min-w-0 flex-col gap-2"
        role="group"
        aria-label="Próximos gastos grandes"
      >
        <h3 className="text-[13px] font-semibold text-ink-2">Próximos gastos grandes (60 días)</h3>
        {overview.data && overview.data.upcoming.length > 0 ? (
          <ul className="flex flex-col">
            {overview.data.upcoming.map((item) => (
              <li
                key={item.id}
                className={cn(ROW_DIVIDER, 'flex items-baseline justify-between gap-3 py-1.5 text-sm')}
              >
                <span className="min-w-0 truncate">
                  {item.name}{' '}
                  <span className="text-muted-foreground">· {monthPhrase(item.due_month)}</span>
                </span>
                <span className="shrink-0 font-semibold tabular-nums">
                  {formatDop(item.amount_cents)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted-foreground">Ninguna reserva vence pronto.</p>
        )}
      </div>
    </section>
  )
}
