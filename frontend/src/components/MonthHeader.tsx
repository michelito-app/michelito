import { ChevronLeft, ChevronRight, Undo2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import type { MonthOption } from '@/lib/api'
import { lastDay, monthName, type Neighbors } from '@/lib/months'
import { FOCUS } from '@/components/summary/styles'
import { MonthPicker } from './MonthPicker'

interface MonthHeaderProps {
  month: string
  label: string
  /** Meses con datos (del más nuevo al más viejo), para la cuadrícula. */
  months: readonly MonthOption[]
  neighbors: Neighbors
  onNavigate: (month: string) => void
  /** Mes por defecto al que se puede volver; null cuando ya se está en él. */
  home: MonthOption | null
  onReturn: () => void
  /** Selector de cuentas, junto al mes. */
  picker?: ReactNode
  /** De qué cuentas son los movimientos: "todas tus cuentas", "VISA ···4242"… */
  scope?: string
  /** Nombre de la pantalla, solo para lectores de pantalla, antes del mes en el título. */
  title?: string
  children?: ReactNode
}

interface ArrowProps {
  target: string | null
  label: string
  onNavigate: (month: string) => void
  children: ReactNode
}

function Arrow({ target, label, onNavigate, children }: ArrowProps) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={target === null}
      onClick={() => target && onNavigate(target)}
      className={cn(
        'flex size-11 shrink-0 items-center justify-center rounded-[10px] border border-border bg-card text-ink-2 transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-card',
        FOCUS,
      )}
    >
      {children}
    </button>
  )
}

/** Título del mes (abre la cuadrícula de meses) con flechas (deshabilitadas en los extremos) y
 * lo que va a la derecha. Lo comparten Resumen y Transacciones. */
export function MonthHeader({
  month,
  label,
  months,
  neighbors,
  onNavigate,
  home,
  onReturn,
  picker,
  scope = 'todas tus cuentas',
  title,
  children,
}: MonthHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <Arrow target={neighbors.older} label="Mes anterior" onNavigate={onNavigate}>
            <ChevronLeft size={16} strokeWidth={2.2} aria-hidden="true" />
          </Arrow>
          <MonthPicker
            month={month}
            label={label}
            options={months}
            onNavigate={onNavigate}
            title={title}
          />
          <Arrow target={neighbors.newer} label="Mes siguiente" onNavigate={onNavigate}>
            <ChevronRight size={16} strokeWidth={2.2} aria-hidden="true" />
          </Arrow>
          {home && (
            <button
              type="button"
              onClick={onReturn}
              className={cn(
                'flex h-11 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-medium text-primary transition-colors hover:bg-muted',
                FOCUS,
              )}
            >
              <Undo2 size={16} strokeWidth={2.2} aria-hidden="true" />
              Volver a {home.label}
            </button>
          )}
          {picker}
        </div>
        <p className="text-sm text-muted-foreground">
          Movimientos del 1 al {lastDay(month)} de {monthName(month)} en {scope} · montos
          en RD$
        </p>
      </div>
      {children}
    </header>
  )
}
