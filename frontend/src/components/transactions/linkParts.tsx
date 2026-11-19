// Piezas compartidas por las secciones de vínculos del detalle (compartido, reembolso, cambio).
import { useEffect, useRef, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import type { LinkedTx } from '@/lib/api'
import { linkedAmount, linkedLabel } from '@/lib/links'
import { cn } from '@/lib/utils'

export const SECTION = 'flex flex-col gap-3 rounded-xl border border-border px-3.5 py-3'
export const SECTION_TITLE =
  'text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase'
export const FIELD =
  'h-11 w-full min-w-0 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30'
const ACTION =
  'h-11 rounded-xl border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2 whitespace-normal'

interface ActionProps {
  onClick: () => void
  disabled?: boolean
  primary?: boolean
  children: ReactNode
  label?: string
  /** Ocupa todo el ancho y el texto puede ir en dos líneas (botones de texto largo). */
  wide?: boolean
  /** Como pestaña de un `tablist`: si es la elegida. */
  tab?: { selected: boolean }
  /** Abre y cierra un panel: si está abierto y su id. */
  disclosure?: { expanded: boolean; controls: string }
}

/** Botón de 44 px de alto (táctil) para las secciones del detalle. */
export function Action({
  onClick,
  disabled,
  primary,
  children,
  label,
  wide,
  tab,
  disclosure,
}: ActionProps) {
  return (
    <Button
      variant={primary ? 'default' : 'outline'}
      className={cn(
        ACTION,
        primary && 'border-transparent bg-primary text-primary-foreground',
        wide && 'h-auto min-h-11 w-full py-2',
      )}
      disabled={disabled}
      onClick={onClick}
      aria-label={label}
      role={tab ? 'tab' : undefined}
      aria-selected={tab ? tab.selected : undefined}
      aria-expanded={disclosure?.expanded}
      aria-controls={disclosure?.expanded ? disclosure.controls : undefined}
    >
      {children}
    </Button>
  )
}

/** Una lista que no cargó: lo dice (con alerta) en vez de mostrarla vacía. */
export function LoadFailure({ what, error }: { what: string; error: Error }) {
  return (
    <p role="alert" className="text-[13px] text-up-ink">
      No se pudieron cargar {what}: {error.message}
    </p>
  )
}

interface ConfirmBoxProps {
  label: string
  confirmLabel: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
  children: ReactNode
}

/** Aviso que pide confirmar: al abrir recibe el foco y al cerrar lo devuelve a donde estaba
 * (el botón que lo abrió). */
export function ConfirmBox({
  label,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
  children,
}: ConfirmBoxProps) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    box.current?.focus()
    return () => opener?.focus()
  }, [])
  return (
    <div
      ref={box}
      role="alertdialog"
      aria-label={label}
      tabIndex={-1}
      className="flex flex-col gap-2 rounded-lg bg-up-soft px-3 py-2.5 text-[13px] text-up-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
    >
      <p>{children}</p>
      <div className="flex flex-wrap gap-2">
        <Action primary disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </Action>
        <Action onClick={onCancel}>Cancelar</Action>
      </div>
    </div>
  )
}

/** Error de una escritura, con rol de alerta. */
export function Failure({ error }: { error: Error | null }) {
  if (error === null) return null
  return (
    <p role="alert" className="text-[13px] text-up-ink">
      No se pudo guardar: {error.message}
    </p>
  )
}

interface LinkedRowProps {
  item: LinkedTx
  action?: ReactNode
  /** Es la transacción abierta: se resalta. */
  current?: boolean
}

/** Resalte de la transacción abierta en una lista del grupo. */
export const CURRENT_ROW = '-mx-2 rounded-lg bg-primary/8 px-2 py-1 ring-1 ring-primary/30'

/** Otra transacción en una línea: comercio (día) · cuenta y monto; a la derecha, su acción. */
export function LinkedRow({ item, action, current }: LinkedRowProps) {
  return (
    <li
      aria-current={current ? 'true' : undefined}
      className={cn(
        'flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]',
        current && CURRENT_ROW,
      )}
    >
      <span className="flex min-w-0 flex-col">
        <span className="font-semibold break-words text-foreground">{linkedLabel(item)}</span>
        <span className="text-muted-foreground">
          {item.account_label} · <span className="tabular-nums">{linkedAmount(item)}</span>
        </span>
      </span>
      {action}
    </li>
  )
}

interface PickListProps {
  items: LinkedTx[]
  chosen: ReadonlySet<string>
  onToggle: (fingerprint: string) => void
  label: string
}

/** Lista con casillas para elegir varias transacciones. */
export function PickList({ items, chosen, onToggle, label }: PickListProps) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="sr-only">{label}</legend>
      {items.map((item) => (
        <label
          key={item.fingerprint}
          className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-1 text-[13px] hover:bg-[#FAFAF8]"
        >
          <input
            type="checkbox"
            checked={chosen.has(item.fingerprint)}
            onChange={() => onToggle(item.fingerprint)}
            className="size-[18px] shrink-0 cursor-pointer accent-primary"
          />
          <span className="flex min-w-0 flex-col">
            <span className="font-semibold break-words">{linkedLabel(item)}</span>
            <span className="text-muted-foreground">
              {item.account_label} · <span className="tabular-nums">{linkedAmount(item)}</span>
            </span>
          </span>
        </label>
      ))}
    </fieldset>
  )
}
