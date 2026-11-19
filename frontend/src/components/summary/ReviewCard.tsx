import { useId, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { Selection } from '@/lib/accountFilter'
import type { InvestmentRole, ReviewItem } from '@/lib/api'
import {
  useChangeInvestment,
  useEditTransaction,
  useMarkReviewed,
  useReview,
} from '@/lib/queries'
import {
  cardTitle,
  itemHref,
  itemKey,
  KIND_LABELS,
  mainAmountText,
  metaText,
  openLabel,
  originalAmountText,
} from '@/lib/review'
import { REVIEW_LIMIT, splitTop } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from './styles'

const NONE: ReadonlySet<string> = new Set()

/** Botón chico con área táctil de 44 px de alto (sin mover lo de al lado). */
const ACTION = cn(
  'relative inline-flex h-8 min-w-11 items-center justify-center rounded-lg border px-3 text-[13px] font-semibold whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50',
  'before:absolute before:-inset-y-1.5 before:inset-x-0 before:content-[""]',
  FOCUS,
)
const PRIMARY = cn(ACTION, 'border-transparent bg-primary text-primary-foreground hover:bg-primary/85')
const SECONDARY = cn(ACTION, 'border-[#D6D6D0] bg-card text-ink-2 hover:bg-muted')

interface ReviewCardProps {
  month: string
  selection?: Selection
}

/** «Para revisar»: lo del mes que conviene mirar (posibles gastos únicos, ingresos inusuales,
 * transferencias grandes, posibles cargos duplicados y subidas de precio), cada aviso en dos
 * líneas con sus acciones. Se ven los primeros y «Ver todos» despliega el resto. Lo revisado sale
 * de la tarjeta; el historial vive en Reportes. */
export function ReviewCard({ month, selection = null }: ReviewCardProps) {
  const review = useReview(month, selection)
  const edit = useEditTransaction()
  const mark = useMarkReviewed()
  const invest = useChangeInvestment()
  const [all, setAll] = useState(false)
  // Lo ya decidido sale de la tarjeta al momento; al llegar datos nuevos manda el servidor.
  const updatedAt = review.dataUpdatedAt
  const [decided, setDecided] = useState<{ at: number; keys: ReadonlySet<string> }>({
    at: updatedAt,
    keys: new Set(),
  })
  const hidden = decided.at === updatedAt ? decided.keys : NONE

  if (review.isPending) return <Skeleton className="h-full min-h-[180px] rounded-2xl" />

  const items = (review.data ?? []).filter((item) => !hidden.has(itemKey(item)))
  const { shown, rest } = splitTop(items, REVIEW_LIMIT, all)

  function hide(item: ReviewItem) {
    setDecided((current) => ({
      at: updatedAt,
      keys: new Set([...(current.at === updatedAt ? current.keys : NONE), itemKey(item)]),
    }))
  }

  function confirmOneOff(item: ReviewItem) {
    edit.mutate(
      { fingerprint: item.fingerprint, body: { one_off: true, scope: 'transaction' } },
      { onSuccess: () => hide(item) },
    )
  }

  /** Un aporte o un cobro posible: lo enlaza a la inversión que se propone. */
  function confirmInvestment(item: ReviewItem, role: InvestmentRole) {
    if (item.investment_id == null) return
    invest.mutate(
      { action: 'add', id: item.investment_id, fingerprint: item.fingerprint, role },
      { onSuccess: () => hide(item) },
    )
  }

  /** Una regla posible: «Siempre» crea la regla del comercio con esa categoría. */
  function acceptRule(item: ReviewItem) {
    if (item.category_id == null) return
    edit.mutate(
      {
        fingerprint: item.fingerprint,
        body: { category_id: item.category_id, scope: 'merchant' },
      },
      { onSuccess: () => hide(item) },
    )
  }

  function reviewed(item: ReviewItem) {
    mark.mutate(
      { kind: item.kind, fingerprint: item.fingerprint, reviewed: true },
      { onSuccess: () => hide(item) },
    )
  }

  if (items.length === 0) {
    return (
      <section
        aria-labelledby="review-title"
        className={cn(PANEL, 'flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3.5 sm:px-6')}
      >
        <h2 id="review-title" className="text-[15px] font-[650] tracking-tight">
          Para revisar
        </h2>
        <p className="text-[13px] text-muted-foreground">
          {review.isError ? `No se pudo cargar: ${review.error.message}` : 'Nada que revisar este mes ✓'}
        </p>
      </section>
    )
  }

  const error = edit.error ?? mark.error ?? invest.error
  const busy = edit.isPending || mark.isPending || invest.isPending
  return (
    <section
      aria-labelledby="review-title"
      className={cn(PANEL, 'flex h-full min-w-0 flex-col gap-2 px-4 py-5 sm:px-6')}
    >
      <div className="flex flex-col gap-1">
        <h2 id="review-title" className={PANEL_TITLE}>
          {cardTitle(items.length)}
        </h2>
        <p className="text-[13px] text-muted-foreground">
          Un gasto único cuenta en el total del mes, no en lo habitual.
        </p>
      </div>
      <ul className="flex flex-col">
        {shown.map((item) => (
          <ReviewLine
            key={itemKey(item)}
            item={item}
            selection={selection}
            busy={busy}
            onReviewed={reviewed}
            onOneOff={confirmOneOff}
            onInvest={confirmInvestment}
            onRule={acceptRule}
          />
        ))}
      </ul>
      {(all || rest.length > 0) && (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll((value) => !value)}
          className={cn(
            '-mx-2 flex min-h-11 items-center self-start rounded-md px-2 text-[13px] font-semibold text-primary hover:bg-muted/60',
            FOCUS,
          )}
        >
          {all ? 'Ver menos' : `Ver todos (${items.length})`}
        </button>
      )}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {error.message}
        </p>
      )}
    </section>
  )
}

interface ReviewLineProps {
  item: ReviewItem
  selection: Selection
  busy: boolean
  onReviewed: (item: ReviewItem) => void
  onOneOff: (item: ReviewItem) => void
  onInvest: (item: ReviewItem, role: InvestmentRole) => void
  onRule: (item: ReviewItem) => void
}

/** Un aviso en dos líneas: tipo, comercio y monto (abren el movimiento en Transacciones); debajo,
 * día, cuenta y motivo en gris, con las acciones a la derecha. */
function ReviewLine({
  item,
  selection,
  busy,
  onReviewed,
  onOneOff,
  onInvest,
  onRule,
}: ReviewLineProps) {
  const reason = useId()
  const original = originalAmountText(item)
  const investing =
    item.investment_id != null &&
    (item.kind === 'aporte_posible' || item.kind === 'cobro_posible')
  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col gap-0.5 py-2')}>
      <Link
        to={itemHref(item, selection)}
        aria-label={openLabel(item)}
        aria-describedby={reason}
        className={cn(
          '-mx-2 flex min-h-11 min-w-0 items-center gap-2 rounded-md px-2 py-1 text-foreground no-underline transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        <Badge className="border border-up/30 bg-up-soft text-up-ink">{KIND_LABELS[item.kind]}</Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={item.description}>
          {item.merchant}
        </span>
        <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums">
          {mainAmountText(item)}
        </span>
      </Link>
      {/* Con tres botones (un cobro posible), la fila se envuelve en vez de salirse. */}
      <div
        className={cn('flex items-start gap-3', investing && 'flex-wrap gap-x-3 gap-y-1.5')}
      >
        <p
          id={reason}
          className={cn(
            'line-clamp-2 min-w-0 flex-1 text-[13px] text-muted-foreground',
            investing && 'basis-48',
          )}
        >
          <span title={item.account_label}>{metaText(item)}</span>
          {original && ` · ${original}`} · {item.reason}
        </p>
        <span className={cn('flex gap-1.5', investing ? 'flex-wrap' : 'shrink-0')}>
          {investing ? (
            <InvestmentButtons item={item} busy={busy} onReviewed={onReviewed} onInvest={onInvest} />
          ) : item.kind === 'regla_posible' ? (
            <>
              <button
                type="button"
                className={PRIMARY}
                aria-label={`Crear regla: ${item.merchant}`}
                disabled={busy}
                onClick={() => onRule(item)}
              >
                Siempre
              </button>
              <button
                type="button"
                className={SECONDARY}
                aria-label={`Descartar regla: ${item.merchant}`}
                disabled={busy}
                onClick={() => onReviewed(item)}
              >
                Descartar
              </button>
            </>
          ) : item.kind === 'unico' ? (
            <>
              <button
                type="button"
                className={PRIMARY}
                aria-label={`Es único: ${item.merchant}`}
                disabled={busy}
                onClick={() => onOneOff(item)}
              >
                Único
              </button>
              <button
                type="button"
                className={SECONDARY}
                aria-label={`No es único: ${item.merchant}`}
                disabled={busy}
                onClick={() => onReviewed(item)}
              >
                No
              </button>
            </>
          ) : (
            <button
              type="button"
              className={SECONDARY}
              aria-label={`Revisado: ${item.merchant}`}
              disabled={busy}
              onClick={() => onReviewed(item)}
            >
              ✓ Revisado
            </button>
          )}
        </span>
      </div>
    </li>
  )
}

type InvestmentButtonsProps = Pick<ReviewLineProps, 'item' | 'busy' | 'onReviewed' | 'onInvest'>

/** ¿Otro aporte? «Aporte» / ¿Cobro? «Rendimiento» o «Capital» (un mixto, desde su pantalla);
 * «No» lo da por revisado. Proponer nunca enlaza: confirmar es este toque. */
function InvestmentButtons({ item, busy, onReviewed, onInvest }: InvestmentButtonsProps) {
  return (
    <>
      {item.kind === 'aporte_posible' ? (
        <button
          type="button"
          className={PRIMARY}
          aria-label={`Sí, es un aporte: ${item.merchant}`}
          disabled={busy}
          onClick={() => onInvest(item, 'contribution')}
        >
          Aporte
        </button>
      ) : (
        <>
          <button
            type="button"
            className={PRIMARY}
            aria-label={`Es rendimiento: ${item.merchant}`}
            disabled={busy}
            onClick={() => onInvest(item, 'return')}
          >
            Rendimiento
          </button>
          <button
            type="button"
            className={SECONDARY}
            aria-label={`Es capital: ${item.merchant}`}
            disabled={busy}
            onClick={() => onInvest(item, 'capital')}
          >
            Capital
          </button>
        </>
      )}
      <button
        type="button"
        className={SECONDARY}
        aria-label={`No es de la inversión: ${item.merchant}`}
        disabled={busy}
        onClick={() => onReviewed(item)}
      >
        No
      </button>
    </>
  )
}
