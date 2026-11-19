import { Link } from 'react-router'
import { FOCUS, ROW_DIVIDER } from '@/components/summary/styles'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Selection } from '@/lib/accountFilter'
import type { InvestmentRole, ReviewItem } from '@/lib/api'
import { useLinkToReserve } from '@/lib/budgetQueries'
import { useChangeInvestment, useEditTransaction } from '@/lib/queries'
import { amountText, itemHref, KIND_LABELS, metaText, openLabel, reviewedLabel } from '@/lib/review'
import { cn } from '@/lib/utils'

const ACTION = 'h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold'
const SECONDARY = cn(ACTION, 'border-[#D6D6D0] bg-card text-ink-2')

interface ReviewRowProps {
  item: ReviewItem
  selection: Selection
  busy: boolean
  /** Marca o desmarca el movimiento como revisado. */
  onReviewed: (item: ReviewItem, reviewed: boolean) => void
  /** Solo en gastos únicos: "Es único" (lo marca como gasto único). */
  onOneOff?: (item: ReviewItem) => void
}

/** Un movimiento para revisar: tipo, enlace a Transacciones, por qué y qué hacer. Lo ya
 * revisado (en el historial) ofrece volver a revisarlo. */
export function ReviewRow({ item, selection, busy, onReviewed, onOneOff }: ReviewRowProps) {
  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="border border-up/30 bg-up-soft text-up-ink">{KIND_LABELS[item.kind]}</Badge>
        {item.reviewed && <Badge className="bg-muted text-muted-foreground">Revisado</Badge>}
      </div>
      {/* Nombre, monto y cuenta abren el movimiento en Transacciones; los botones no. */}
      <Link
        to={itemHref(item, selection)}
        aria-label={openLabel(item)}
        className={cn(
          '-mx-2 flex min-w-0 flex-col gap-0.5 rounded-md px-2 py-1 text-foreground no-underline transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={item.description}>
            {item.merchant}
          </span>
          <span aria-hidden="true" className="shrink-0 text-sm text-muted-foreground">
            →
          </span>
        </span>
        <span className="text-sm font-semibold whitespace-nowrap tabular-nums">{amountText(item)}</span>
        <span className="truncate text-[13px] text-muted-foreground" title={item.account_label}>
          {metaText(item)}
        </span>
      </Link>
      <p className="text-[13px] text-ink-2">{item.reason}</p>
      <div className="flex flex-wrap gap-2">
        {item.reviewed ? (
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={`Volver a revisar: ${item.merchant}`}
            disabled={busy}
            onClick={() => onReviewed(item, false)}
          >
            Volver a revisar
          </Button>
        ) : item.investment_id != null &&
          (item.kind === 'aporte_posible' || item.kind === 'cobro_posible') ? (
          <InvestmentActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'reserva_posible' && item.reserve_id != null ? (
          <ReserveActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'regla_posible' && item.category_id != null ? (
          <RuleActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'unico' ? (
          <>
            <Button
              className={ACTION}
              aria-label={`Es único: ${item.merchant}`}
              disabled={busy || !onOneOff}
              onClick={() => onOneOff?.(item)}
            >
              Es único
            </Button>
            <Button
              variant="outline"
              className={SECONDARY}
              aria-label={reviewedLabel(item)}
              disabled={busy}
              onClick={() => onReviewed(item, true)}
            >
              No es único
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={reviewedLabel(item)}
            disabled={busy}
            onClick={() => onReviewed(item, true)}
          >
            {item.kind === 'regla_posible' ? 'Descartar' : 'Ya lo revisé'}
          </Button>
        )}
      </div>
    </li>
  )
}

interface InvestmentActionsProps {
  item: ReviewItem
  busy: boolean
  onReviewed: (item: ReviewItem, reviewed: boolean) => void
}

/** Un aporte o un cobro posible: confirmarlo es un toque (lo enlaza a la inversión que se
 * propone); «No es» lo da por revisado. Un cobro mixto se marca desde su pantalla. */
function InvestmentActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const change = useChangeInvestment()
  const link = (role: InvestmentRole) =>
    change.mutate({
      action: 'add',
      id: item.investment_id!,
      fingerprint: item.fingerprint,
      role,
    })
  const pending = busy || change.isPending
  return (
    <>
      {item.kind === 'aporte_posible' ? (
        <Button
          className={ACTION}
          aria-label={`Sí, es un aporte: ${item.merchant}`}
          disabled={pending}
          onClick={() => link('contribution')}
        >
          Sí, es un aporte
        </Button>
      ) : (
        <>
          <Button
            className={ACTION}
            aria-label={`Es rendimiento: ${item.merchant}`}
            disabled={pending}
            onClick={() => link('return')}
          >
            Es rendimiento
          </Button>
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={`Es capital: ${item.merchant}`}
            disabled={pending}
            onClick={() => link('capital')}
          >
            Es capital
          </Button>
        </>
      )}
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={`No es de la inversión: ${item.merchant}`}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        No es
      </Button>
      {change.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          No se pudo guardar: {change.error.message}
        </p>
      )}
    </>
  )
}

/** Una regla posible: «Siempre» crea la regla del comercio con la categoría propuesta (queda en
 * la bitácora); «Descartar» no la vuelve a proponer. */
function RuleActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const edit = useEditTransaction()
  const pending = busy || edit.isPending
  return (
    <>
      <Button
        className={ACTION}
        aria-label={`Crear regla: ${item.merchant}`}
        disabled={pending}
        onClick={() =>
          edit.mutate({
            fingerprint: item.fingerprint,
            body: { category_id: item.category_id!, scope: 'merchant' },
          })
        }
      >
        Siempre
      </Button>
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={reviewedLabel(item)}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        Descartar
      </Button>
      {edit.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          No se pudo guardar: {edit.error.message}
        </p>
      )}
    </>
  )
}

/** Un gasto que parece de una reserva: «Sí, es de la reserva» lo vincula (sale del tope de su
 * categoría); «No» lo da por revisado y no vuelve. */
function ReserveActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const link = useLinkToReserve()
  const pending = busy || link.isPending
  return (
    <>
      <Button
        className={ACTION}
        aria-label={`Sí, es de la reserva: ${item.merchant}`}
        disabled={pending}
        onClick={() => link.mutate({ id: item.reserve_id!, fingerprints: [item.fingerprint] })}
      >
        Sí, es de la reserva
      </Button>
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={`No es de la reserva: ${item.merchant}`}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        No
      </Button>
      {link.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          No se pudo guardar: {link.error.message}
        </p>
      )}
    </>
  )
}
