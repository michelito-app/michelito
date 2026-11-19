import { ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import { Link } from 'react-router'
import { FOCUS, ROW_DIVIDER } from '@/components/summary/styles'
import type { SharedListGroup } from '@/lib/api'
import { formatMoney, linkPagePath, splitText } from '@/lib/links'
import { shortDay } from '@/lib/months'
import {
  excessText,
  expenseState,
  groupMeta,
  moneyLine,
  refundLabel,
  statusText,
} from '@/lib/sharedList'
import { cn } from '@/lib/utils'

const STATUS_CLASS: Record<SharedListGroup['status'], string> = {
  pending: 'text-foreground',
  settled: 'text-down',
  written_off: 'text-muted-foreground',
}

const MANAGE =
  'inline-flex min-h-11 items-center rounded-xl border border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2 no-underline hover:bg-muted'

interface GroupRowProps {
  group: SharedListGroup
  expanded: boolean
  onToggle: () => void
  /** La URL a la que vuelve «Volver» desde la pantalla del grupo (con este desplegado). */
  from: string
  /** Al llegar con este grupo desplegado (al volver de su pantalla): se muestra en pantalla y
   * su fila recibe el foco; luego avisa (`onRevealed`) para no hacerlo otra vez. */
  reveal: boolean
  onRevealed: () => void
}

/** Un grupo de Compartidos: tocarlo lo despliega con sus gastos y reembolsos; «Gestionar…»
 * abre la pantalla del grupo. La lista es solo lectura. */
export function GroupRow({
  group,
  expanded,
  onToggle,
  from,
  reveal,
  onRevealed,
}: GroupRowProps) {
  const ids = useId()
  const row = useRef<HTMLLIElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const status = statusText(group)
  const excess = excessText(group)

  useEffect(() => {
    if (!reveal) return
    button.current?.focus({ preventScroll: true })
    row.current?.scrollIntoView({ block: 'center' })
    onRevealed()
  }, [reveal, onRevealed])

  return (
    <li ref={row} className={ROW_DIVIDER}>
      <button
        ref={button}
        type="button"
        aria-expanded={expanded}
        aria-controls={expanded ? `${ids}-detail` : undefined}
        onClick={onToggle}
        className={cn(
          '-mx-2 flex w-[calc(100%+1rem)] min-w-0 items-center gap-3 rounded-md px-2 py-3 text-left transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3">
            <span className="min-w-0 truncate text-sm font-semibold">{group.title}</span>
            <span
              data-testid="group-status"
              className={cn(
                'ml-auto text-sm font-semibold whitespace-nowrap tabular-nums',
                STATUS_CLASS[group.status],
              )}
            >
              {status.main}
            </span>
          </span>
          <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 text-[13px] text-muted-foreground">
            <span className="min-w-0 flex-[1_1_200px] break-words">{groupMeta(group)}</span>
            {status.approx && (
              <span className="ml-auto whitespace-nowrap tabular-nums">{status.approx}</span>
            )}
          </span>
          <span className="text-[13px] break-words text-muted-foreground tabular-nums">
            {moneyLine(group)}
          </span>
          {excess && <span className="text-[13px] font-medium text-up-ink">{excess}</span>}
        </span>
        <ChevronDown
          size={16}
          aria-hidden="true"
          className={cn(
            'shrink-0 text-muted-foreground transition-transform',
            expanded && 'rotate-180',
          )}
        />
      </button>
      {expanded && (
        <div id={`${ids}-detail`} className="flex flex-col gap-3 pt-1 pb-4">
          <Details group={group} />
          <div>
            <Link
              to={linkPagePath(group.first_fingerprint)}
              state={{ from }}
              aria-label={`Gestionar ${group.title}`}
              className={cn(MANAGE, FOCUS)}
            >
              Gestionar…
            </Link>
          </div>
        </div>
      )}
    </li>
  )
}

const LIST_TITLE = 'text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase'

function Details({ group }: { group: SharedListGroup }) {
  return (
    <>
      <section aria-label={`Gastos de ${group.title}`} className="flex flex-col gap-1.5">
        <h3 className={LIST_TITLE}>Gastos</h3>
        <ul className="flex flex-col gap-2">
          {group.expenses.map((e) => (
            <li key={e.fingerprint} className="flex flex-col text-[13px]">
              <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="min-w-0 font-semibold break-words">
                  {e.merchant}{' '}
                  <span className="font-normal text-muted-foreground">({shortDay(e.day)})</span>
                </span>
                <span className="ml-auto font-semibold whitespace-nowrap tabular-nums">
                  {formatMoney(e.amount_cents, e.currency)}
                </span>
              </span>
              <span className="text-muted-foreground">
                {splitText(e, e.currency)} · {e.account_label} · {expenseState(e)}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-label={`Reembolsos de ${group.title}`} className="flex flex-col gap-1.5">
        <h3 className={LIST_TITLE}>Reembolsos</h3>
        {group.refunds.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Aún no te han devuelto nada.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {group.refunds.map((r) => (
              <li
                key={r.key}
                className="flex flex-wrap items-baseline justify-between gap-x-3 text-[13px]"
              >
                <span className="min-w-0 break-words">
                  <span className="text-muted-foreground">{shortDay(r.day)} · </span>
                  {refundLabel(r)}
                </span>
                <span className="ml-auto font-semibold whitespace-nowrap tabular-nums">
                  {formatMoney(r.amount_cents, r.currency)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
