import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'
import { FOCUS } from '@/components/summary/styles'
import type { MonthOption } from '@/lib/api'
import {
  adjacentYear,
  GRID_COLUMNS,
  gridYears,
  type MonthCell,
  monthCells,
  moveFocus,
} from '@/lib/monthGrid'
import { localToday } from '@/lib/months'
import { cn } from '@/lib/utils'

interface MonthPickerProps {
  month: string
  label: string
  options: readonly MonthOption[]
  onNavigate: (month: string) => void
  /** Texto solo para lectores de pantalla antes del mes en el título ("Transacciones"). */
  title?: string
}

const KEY_STEPS: Record<string, number> = {
  ArrowLeft: -1,
  ArrowRight: 1,
  ArrowUp: -GRID_COLUMNS,
  ArrowDown: GRID_COLUMNS,
}

/** Por debajo de `sm` (640 px) la cuadrícula es una hoja inferior modal. */
const PHONE_QUERY = '(max-width: 639.98px)'
/** Lo que se alcanza con Tab dentro de la hoja (los meses usan foco itinerante). */
const TABBABLE = 'button:not([disabled]):not([tabindex="-1"])'

function subscribePhone(onChange: () => void): () => void {
  const query = window.matchMedia(PHONE_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribePhone,
    () => window.matchMedia(PHONE_QUERY).matches,
    () => false,
  )
}

/** En la hoja modal, Tab y Mayús+Tab dan la vuelta dentro de `panel`. */
function trapTab(event: KeyboardEvent<HTMLDivElement>, panel: HTMLElement | null): void {
  if (event.key !== 'Tab' || panel === null) return
  const items = [...panel.querySelectorAll<HTMLElement>(TABBABLE)]
  if (items.length === 0) return
  const first = items[0]
  const last = items[items.length - 1]
  const at = document.activeElement
  if (event.shiftKey && (at === first || !panel.contains(at))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (at === last || !panel.contains(at))) {
    event.preventDefault()
    first.focus()
  }
}

function yearOf(month: string): number {
  return Number(month.slice(0, 4))
}

/** Título del mes ("Noviembre 2026 ▾") que abre la cuadrícula del año: popover desde `sm`,
 * hoja inferior en teléfono. */
export function MonthPicker({ month, label, options, onNavigate, title }: MonthPickerProps) {
  const [open, setOpen] = useState(false)
  const [year, setYear] = useState(() => yearOf(month))
  const wrapper = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  function close(returnFocus: boolean) {
    setOpen(false)
    if (returnFocus) trigger.current?.focus()
  }

  // Clic (o toque) fuera cierra.
  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    // El foco se fue a otra parte de la página (Tab): cierra. Si se perdió (null), no.
    const next = event.relatedTarget
    if (open && next instanceof Node && !wrapper.current?.contains(next)) setOpen(false)
  }

  return (
    <div ref={wrapper} className="relative min-w-0" onBlur={onBlur}>
      <h1 className="min-w-0 text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
        {title && <span className="sr-only">{title}: </span>}
        <button
          ref={trigger}
          type="button"
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={() => {
            if (open) return close(false)
            setYear(yearOf(month))
            setOpen(true)
          }}
          onKeyDown={(event) => {
            if (event.key !== 'Escape' || !open) return
            event.stopPropagation()
            close(true)
          }}
          className={cn(
            'flex min-h-11 max-w-full items-center gap-1.5 rounded-[10px] px-1.5 text-left transition-colors hover:bg-muted aria-expanded:bg-muted',
            FOCUS,
          )}
        >
          <span className="min-w-0">{label}</span>
          <ChevronDown
            size={20}
            strokeWidth={2.4}
            aria-hidden="true"
            className={cn(
              'shrink-0 text-muted-foreground transition-transform',
              open && 'rotate-180',
            )}
          />
        </button>
      </h1>
      {open && (
        <MonthPanel
          id={panelId}
          month={month}
          year={year}
          options={options}
          onYear={setYear}
          onPick={(target) => {
            close(true)
            if (target !== month) onNavigate(target)
          }}
          onClose={close}
        />
      )}
    </div>
  )
}

interface MonthPanelProps {
  id: string
  month: string
  year: number
  options: readonly MonthOption[]
  onYear: (year: number) => void
  onPick: (month: string) => void
  onClose: (returnFocus: boolean) => void
}

function MonthPanel({ id, month, year, options, onYear, onPick, onClose }: MonthPanelProps) {
  const grid = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const phone = useIsPhone()
  const yearId = useId()
  const years = gridYears(options)
  const older = adjacentYear(years, year, -1)
  const newer = adjacentYear(years, year, 1)
  const cells = monthCells(options, year, localToday().slice(0, 7))
  const selectedAt = cells.findIndex((c) => c.month === month)
  // El mes que recibe el foco con Tab: el elegido si está en este año; si no, el primero con
  // datos.
  const anchor = selectedAt >= 0 ? selectedAt : cells.findIndex((c) => c.enabled)

  // Al abrir, el foco va al mes elegido.
  useEffect(() => {
    grid.current?.querySelector<HTMLButtonElement>('[data-anchor]')?.focus()
  }, [])

  function onGridKey(event: KeyboardEvent<HTMLDivElement>) {
    const from = Number((event.target as HTMLElement).dataset.index)
    if (Number.isNaN(from)) return
    let to: number | null = null
    if (event.key in KEY_STEPS) to = moveFocus(cells, from, KEY_STEPS[event.key])
    if (event.key === 'Home') to = cells.findIndex((c) => c.enabled)
    if (event.key === 'End') to = cells.findLastIndex((c) => c.enabled)
    if (to === null) return
    event.preventDefault()
    grid.current?.querySelector<HTMLButtonElement>(`[data-index="${to}"]`)?.focus()
  }

  return (
    <>
      <div
        aria-hidden="true"
        onClick={() => onClose(true)}
        className="fixed inset-0 z-40 bg-[#1B1D21]/30 animate-in fade-in-0 sm:hidden"
      />
      <div
        ref={panel}
        id={id}
        role="dialog"
        aria-label="Elegir mes"
        aria-modal={phone || undefined}
        onKeyDown={(event) => {
          if (phone) trapTab(event, panel.current)
          if (event.key !== 'Escape') return
          event.stopPropagation()
          onClose(true)
        }}
        className={cn(
          'z-50 flex flex-col gap-3 border border-border bg-card p-4 text-base font-normal tracking-normal text-foreground',
          // Teléfono: hoja inferior.
          'fixed inset-x-0 bottom-0 rounded-t-2xl pb-[max(16px,env(safe-area-inset-bottom))] shadow-[0_-8px_32px_rgba(27,29,33,0.16)] animate-in slide-in-from-bottom-8 fade-in-0 duration-200',
          // Desde sm: popover bajo el título.
          'sm:absolute sm:inset-x-auto sm:bottom-auto sm:top-full sm:left-0 sm:mt-2 sm:w-[320px] sm:rounded-xl sm:pb-4 sm:shadow-[0_8px_32px_rgba(27,29,33,0.16)] sm:slide-in-from-bottom-0 sm:zoom-in-95',
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <YearArrow target={older} label="Año anterior" onYear={onYear}>
            <ChevronLeft size={16} strokeWidth={2.2} aria-hidden="true" />
          </YearArrow>
          <span id={yearId} className="text-[15px] font-semibold tabular-nums" aria-live="polite">
            {year}
          </span>
          <YearArrow target={newer} label="Año siguiente" onYear={onYear}>
            <ChevronRight size={16} strokeWidth={2.2} aria-hidden="true" />
          </YearArrow>
        </div>
        <div
          ref={grid}
          role="group"
          aria-labelledby={yearId}
          onKeyDown={onGridKey}
          className="grid grid-cols-3 gap-1.5"
        >
          {cells.map((cell, index) => (
            <MonthButton
              key={cell.month}
              cell={cell}
              index={index}
              selected={index === selectedAt}
              anchor={index === anchor}
              onPick={onPick}
            />
          ))}
        </div>
      </div>
    </>
  )
}

interface YearArrowProps {
  target: number | null
  label: string
  onYear: (year: number) => void
  children: ReactNode
}

/** Con `aria-disabled` y no `disabled`: el foco no se pierde al llegar al último año. */
function YearArrow({ target, label, onYear, children }: YearArrowProps) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-disabled={target === null}
      onClick={() => target !== null && onYear(target)}
      className={cn(
        'flex size-11 shrink-0 items-center justify-center rounded-[10px] border border-border bg-card text-ink-2 transition-colors hover:bg-muted aria-disabled:cursor-not-allowed aria-disabled:opacity-40 aria-disabled:hover:bg-card',
        FOCUS,
      )}
    >
      {children}
    </button>
  )
}

interface MonthButtonProps {
  cell: MonthCell
  index: number
  selected: boolean
  anchor: boolean
  onPick: (month: string) => void
}

function MonthButton({ cell, index, selected, anchor, onPick }: MonthButtonProps) {
  return (
    <button
      type="button"
      data-index={index}
      data-anchor={anchor || undefined}
      tabIndex={anchor ? 0 : -1}
      disabled={!cell.enabled}
      aria-label={cell.current ? `${cell.label} (mes en curso)` : cell.label}
      aria-current={selected ? 'date' : undefined}
      onClick={() => onPick(cell.month)}
      className={cn(
        'relative flex h-11 items-center justify-center rounded-lg text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:font-medium disabled:text-muted-foreground/60',
        selected
          ? 'bg-primary text-primary-foreground'
          : 'text-foreground enabled:hover:bg-muted',
        cell.current && !selected && 'ring-1 ring-primary/50 ring-inset',
        FOCUS,
      )}
    >
      {cell.short}
      {cell.current && (
        <span
          aria-hidden="true"
          className={cn(
            'absolute bottom-1.5 size-1 rounded-full',
            selected ? 'bg-primary-foreground' : 'bg-primary',
          )}
        />
      )}
    </button>
  )
}
