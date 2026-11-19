import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import { Action, ConfirmBox, Failure } from '@/components/transactions/linkParts'
import type { CashBox, CashEntryKind, CashLine } from '@/lib/api'
import {
  approxText,
  balanceText,
  CASH_BOX_ID,
  deleteWarning,
  isNegative,
  LINE_LABELS,
  lineAmount,
  lineDetail,
  lineHref,
} from '@/lib/cashBox'
import { shortDay } from '@/lib/links'
import { useCashBox, useChangeCashBox } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { CashEntryForm } from './CashEntryForm'

const SHOWN = 8

/** La tarjeta «Caja fuerte» de Cuentas: saldo por moneda y ≈ RD$, avisos, botones para anotar y
 * la lista de entradas y salidas. */
export function CashBoxCard({ today }: { today: string }) {
  const box = useCashBox()
  const section = useRef<HTMLElement>(null)
  const location = useLocation()
  const loaded = box.isSuccess

  // Desde el Resumen («fueron a la caja fuerte») se llega con #caja-fuerte.
  useEffect(() => {
    if (loaded && location.hash === `#${CASH_BOX_ID}`) {
      section.current?.scrollIntoView({ block: 'start' })
    }
  }, [loaded, location.hash])

  return (
    <section
      ref={section}
      id={CASH_BOX_ID}
      aria-label="Caja fuerte"
      className={cn(PANEL, 'flex min-w-0 flex-col gap-4 px-5 py-4')}
    >
      <h2 className={PANEL_TITLE}>Caja fuerte</h2>
      {box.isError && (
        <LoadError what="la caja fuerte" error={box.error} onRetry={() => box.refetch()} />
      )}
      {box.isPending && <Skeleton className="h-24 rounded-xl" />}
      {box.isSuccess && <Contents box={box.data} today={today} />}
    </section>
  )
}

function Contents({ box, today }: { box: CashBox; today: string }) {
  const [form, setForm] = useState<CashEntryKind | null>(null)
  const [editing, setEditing] = useState<CashLine | null>(null)
  const [all, setAll] = useState(false)
  const approx = approxText(box)
  const shown = all ? box.lines : box.lines.slice(0, SHOWN)

  function open(kind: CashEntryKind) {
    setEditing(null)
    setForm(kind)
  }

  return (
    <>
      <div className="flex flex-col gap-1">
        <span className="text-[13px] text-muted-foreground">Saldo</span>
        <span
          data-testid="cash-box-balance"
          className="text-[24px] leading-tight font-bold tabular-nums break-words"
        >
          {balanceText(box.balances)}
        </span>
        {approx && (
          <span data-testid="cash-box-approx" className="text-[13px] text-ink-2">
            {approx}
          </span>
        )}
        <span className="text-[13px] text-muted-foreground">
          Efectivo guardado: no cuenta como gasto hasta que lo uses.
        </span>
      </div>
      {box.negative.map((item) => (
        <div
          key={item.currency}
          role="status"
          className="flex flex-col gap-2 rounded-lg bg-up-soft px-3 py-2.5 text-[13px] text-up-ink"
        >
          <p data-testid="cash-box-negative">{isNegative(item)}</p>
          <div>
            <Action onClick={() => open('initial')}>Ajustar el saldo inicial…</Action>
          </div>
        </div>
      ))}
      {box.uncounted.length > 0 && (
        <p className="text-[13px] text-muted-foreground">
          {box.uncounted.length === 1 ? 'Un depósito' : `${box.uncounted.length} depósitos`} en
          otra moneda sin tasa del mes no bajan el saldo.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Action onClick={() => open('expense')}>Registrar salida…</Action>
        <Action onClick={() => open('income')}>Registrar entrada…</Action>
        <Action onClick={() => open('initial')}>Saldo inicial…</Action>
      </div>
      {form && (
        <CashEntryForm
          key={`${form}-${editing?.fingerprint ?? 'nueva'}`}
          kind={form}
          box={box}
          today={today}
          editing={editing}
          onDone={() => {
            setForm(null)
            setEditing(null)
          }}
        />
      )}
      {box.lines.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Aún no hay movimientos. Marca un retiro con «Lo guardé en la caja fuerte» en su
          detalle, o anota el saldo inicial.
        </p>
      ) : (
        <ul aria-label="Movimientos de la caja fuerte" className="flex flex-col">
          {shown.map((line) => (
            <LineRow
              key={line.fingerprint}
              line={line}
              onEdit={() => {
                setEditing(line)
                setForm(line.kind as CashEntryKind)
              }}
            />
          ))}
        </ul>
      )}
      {box.lines.length > SHOWN && (
        <div>
          <Action onClick={() => setAll(!all)}>
            {all ? 'Ver menos' : `Ver todos (${box.lines.length})`}
          </Action>
        </div>
      )}
    </>
  )
}

function LineRow({ line, onEdit }: { line: CashLine; onEdit: () => void }) {
  const remove = useChangeCashBox()
  const [confirming, setConfirming] = useState(false)
  const detail = lineDetail(line)
  const manual = line.entry_id !== null
  return (
    <li className="flex flex-col gap-2 border-b border-[#F2F2EE] py-2.5 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-sm font-semibold">
            {LINE_LABELS[line.kind]}{' '}
            <span className="font-normal text-muted-foreground">· {shortDay(line.day)}</span>
          </span>
          {detail && <span className="text-[13px] break-words text-ink-2">{detail}</span>}
        </div>
        <span
          className={cn(
            'shrink-0 text-sm font-semibold tabular-nums',
            (line.amount_cents ?? 0) < 0 ? 'text-ink-2' : 'text-primary',
          )}
        >
          {lineAmount(line)}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {line.in_flow && (
          <Link
            to={lineHref(line)}
            aria-label={`Ver en Transacciones: ${LINE_LABELS[line.kind]} del ${shortDay(line.day)}`}
            className="inline-flex min-h-11 items-center rounded-md px-2 text-[13px] font-semibold text-primary hover:bg-muted/60"
          >
            Ver en Transacciones
          </Link>
        )}
        {manual && (
          <>
            <Action onClick={onEdit} label={`Editar ${LINE_LABELS[line.kind].toLowerCase()}`}>
              Editar
            </Action>
            <Action
              onClick={() => setConfirming(true)}
              label={`Borrar ${LINE_LABELS[line.kind].toLowerCase()}`}
            >
              Borrar
            </Action>
          </>
        )}
      </div>
      {confirming && line.entry_id !== null && (
        <ConfirmBox
          label="Borrar el movimiento"
          confirmLabel="Sí, borrar"
          busy={remove.isPending}
          onConfirm={() => remove.mutate({ action: 'delete', id: line.entry_id! })}
          onCancel={() => setConfirming(false)}
        >
          {deleteWarning(line.group)}
        </ConfirmBox>
      )}
      <Failure error={remove.error} />
    </li>
  )
}
