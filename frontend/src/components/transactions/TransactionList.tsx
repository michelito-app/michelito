import { ChevronRight, StickyNote } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { Tx } from '@/lib/api'
import { shortAccountLabel, splitLabel } from '@/lib/accounts'
import { colorFor, customColors } from '@/lib/categories'
import { type LinkBadge, linkBadges } from '@/lib/links'
import { useCategories } from '@/lib/queries'
import {
  AMOUNT_TONE_CLASS,
  amountLines,
  amountTone,
  dayGroups,
  fieldGroups,
  groupLine,
  kindBadge,
  oneOffBadge,
  outOfView,
  type FieldGroup,
  type GroupBy,
  type SortBy,
} from '@/lib/transactions'
import { visibleRows } from '@/lib/selection'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL } from '@/components/summary/styles'

// Una sola línea desde @xl: comercio (con sus insignias) | categoría | cuenta | monto (con el
// original en US$ al lado). Más angosto, dos líneas: comercio y monto; debajo categoría · cuenta.
const GRID =
  'grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 @xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(9.5rem,auto)] @xl:gap-x-3.5'

// Encabezados de día y de grupo: se quedan arriba mientras se recorre su grupo.
const STICKY_HEADER = 'sticky top-0 z-10 border-b border-[#EFEFEA] bg-[#FAFAF8]'

interface TransactionListProps {
  items: Tx[]
  selected: string | null
  ranking: readonly string[]
  stale: boolean
  group: GroupBy
  sort: SortBy
  onSelect: (tx: Tx) => void
  /** Modo «Seleccionar»: cada fila es una casilla (`chosen`) en vez de abrir el detalle. */
  picking?: Picking | null
}

export interface Picking {
  chosen: ReadonlySet<string>
  onToggle: (tx: Tx) => void
  /** Las filas que se ven (con grupos, solo las de los abiertos), cada vez que cambian. */
  onVisible: (fingerprints: string[]) => void
}

/** Lista agrupada por día, categoría o comercio; cada fila es un botón que abre el detalle (o,
 * al seleccionar, una casilla). */
export function TransactionList({
  items,
  selected,
  ranking,
  stale,
  group,
  sort,
  onSelect,
  picking = null,
}: TransactionListProps) {
  const rowProps = { selected, ranking, onSelect, picking }
  const section = useRef<HTMLElement>(null)
  // Al cambiar la fila elegida (también al llegar desde el Resumen, Pendientes o «Volver») la
  // lista la trae a la vista si no se ve; plegar o desplegar un grupo no la mueve.
  useEffect(() => {
    if (!selected) return
    const row = section.current?.querySelector<HTMLElement>(
      `[data-fingerprint="${CSS.escape(selected)}"]`,
    )
    if (row) bringIntoView(row)
  }, [selected])
  const onVisible = picking?.onVisible
  // Por día se ve todo; por grupos, lo avisa `FieldGroups` según los que estén abiertos.
  useEffect(() => {
    if (onVisible && group === 'day') onVisible(items.map((t) => t.fingerprint))
  }, [onVisible, group, items])
  const groups = useMemo(
    () =>
      group === 'day'
        ? { kind: 'day' as const, days: dayGroups(items, sort) }
        : { kind: 'field' as const, field: group, fields: fieldGroups(items, group, sort) },
    [items, group, sort],
  )
  return (
    <section
      ref={section}
      aria-label="Lista de transacciones"
      aria-busy={stale}
      className={cn(
        PANEL,
        // `clip` y no `hidden`: recorta las esquinas sin romper los encabezados fijos.
        '@container min-w-0 flex-[3_1_560px] overflow-clip transition-opacity',
        stale && 'opacity-60',
      )}
    >
      {groups.kind === 'day' ? (
        groups.days.map((day) => (
          <div key={day.day} role="group" aria-label={day.label}>
            <div
              data-day-header
              className={cn(
                STICKY_HEADER,
                'px-4 py-2 text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase sm:px-5',
              )}
            >
              {day.label}
            </div>
            <Rows items={day.items} {...rowProps} />
          </div>
        ))
      ) : (
        // Al cambiar de agrupación se cierran todos los grupos.
        <FieldGroups
          key={groups.field}
          groups={groups.fields}
          field={groups.field}
          {...rowProps}
        />
      )}
    </section>
  )
}

/** Centra la fila si no se ve entera. En el teléfono la hoja de detalle la tapa casi toda: lo
 * que importa es que quede a la vista al cerrarla. */
function bringIntoView(row: HTMLElement) {
  if (!outOfView(row.getBoundingClientRect(), window.innerHeight)) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  row.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' })
}

interface RowsProps {
  items: Tx[]
  selected: string | null
  ranking: readonly string[]
  onSelect: (tx: Tx) => void
  picking: Picking | null
}

function Rows({ items, selected, ranking, onSelect, picking }: RowsProps) {
  const custom = customColors(useCategories().data ?? [])
  return items.map((tx) =>
    picking ? (
      <PickRow
        key={tx.fingerprint}
        tx={tx}
        color={colorFor(ranking, tx.category, custom)}
        checked={picking.chosen.has(tx.fingerprint)}
        onToggle={picking.onToggle}
      />
    ) : (
      <Row
        key={tx.fingerprint}
        tx={tx}
        color={colorFor(ranking, tx.category, custom)}
        selected={tx.fingerprint === selected}
        onSelect={onSelect}
      />
    ),
  )
}

interface FieldGroupsProps extends Omit<RowsProps, 'items'> {
  groups: FieldGroup[]
  field: 'category' | 'merchant'
}

/** Grupos por categoría o comercio, cerrados al empezar (salvo el de la fila elegida). */
function FieldGroups({ groups, field, selected, ranking, onSelect, picking }: FieldGroupsProps) {
  const custom = customColors(useCategories().data ?? [])
  const baseId = useId()
  const [open, setOpen] = useState<ReadonlySet<string>>(() => {
    const chosen = groups.find((g) => g.items.some((t) => t.fingerprint === selected))
    return new Set(chosen ? [chosen.key] : [])
  })
  const onVisible = picking?.onVisible
  useEffect(() => {
    if (onVisible) onVisible(visibleRows(groups, open).map((t) => t.fingerprint))
  }, [onVisible, groups, open])

  function toggle(key: string) {
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })
  }

  return groups.map((group, index) => {
    const expanded = open.has(group.key)
    const panelId = `${baseId}-${index}`
    return (
      <div key={group.key} role="group" aria-label={group.key}>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => toggle(group.key)}
          className={cn(
            STICKY_HEADER,
            'flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left hover:bg-[#F4F4F0] sm:px-5',
            FOCUS,
            'focus-visible:ring-inset',
          )}
        >
          <ChevronRight
            size={16}
            aria-hidden="true"
            className={cn(
              'shrink-0 text-muted-foreground transition-transform',
              expanded && 'rotate-90',
            )}
          />
          {field === 'category' && <Swatch color={colorFor(ranking, group.key, custom)} />}
          <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
            <span className="max-w-full truncate text-sm font-semibold text-foreground">
              {group.key}
            </span>{' '}
            <span className="text-xs text-muted-foreground tabular-nums">{groupLine(group)}</span>
          </span>
        </button>
        <div id={panelId} hidden={!expanded}>
          {expanded && (
            <Rows
              items={group.items}
              selected={selected}
              ranking={ranking}
              onSelect={onSelect}
              picking={picking}
            />
          )}
        </div>
      </div>
    )
  })
}

interface RowProps {
  tx: Tx
  color: string
  selected: boolean
  onSelect: (tx: Tx) => void
}

function Row({ tx, color, selected, onSelect }: RowProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      data-fingerprint={tx.fingerprint}
      onClick={() => onSelect(tx)}
      className={cn(
        GRID,
        'relative min-h-11 w-full scroll-mt-16 cursor-pointer items-center border-b border-[#F2F2EE] px-4 py-1.5 text-left text-foreground transition-colors last:border-b-0 sm:px-5',
        selected ? 'bg-[#F1F7F5]' : 'bg-card hover:bg-[#FAFAF8]',
        FOCUS,
        'focus-visible:ring-inset',
      )}
    >
      {selected && (
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
      )}
      <RowBody tx={tx} color={color} />
    </button>
  )
}

interface PickRowProps {
  tx: Tx
  color: string
  checked: boolean
  onToggle: (tx: Tx) => void
}

/** Una fila en el modo «Seleccionar»: la casilla (44 px) y lo mismo que la fila normal; tocar
 * cualquier parte la marca o desmarca. */
function PickRow({ tx, color, checked, onToggle }: PickRowProps) {
  return (
    <label
      data-fingerprint={tx.fingerprint}
      className={cn(
        'relative flex min-h-11 w-full cursor-pointer items-stretch border-b border-[#F2F2EE] text-foreground transition-colors last:border-b-0 focus-within:ring-3 focus-within:ring-ring/30 focus-within:ring-inset',
        checked ? 'bg-[#F1F7F5]' : 'bg-card hover:bg-[#FAFAF8]',
      )}
    >
      <span className="flex w-11 shrink-0 items-center justify-center">
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(tx)}
          aria-label={pickLabel(tx)}
          className="size-5 cursor-pointer accent-[var(--color-primary)]"
        />
      </span>
      <span className={cn(GRID, 'min-w-0 flex-1 items-center py-1.5 pr-4 sm:pr-5')}>
        <RowBody tx={tx} color={color} />
      </span>
    </label>
  )
}

/** «Seleccionar 8 ene MB DESDE … +RD$ 12,000»: el día distingue dos iguales. */
function pickLabel(tx: Tx): string {
  return `Seleccionar ${shortDay(tx.day)} ${tx.merchant} ${amountLines(tx).main}`
}

/** Lo que muestra una fila (en la rejilla `GRID` de quien la contiene). */
function RowBody({ tx, color }: { tx: Tx; color: string }) {
  const amount = amountLines(tx)
  return (
    <>
      <span className="col-start-1 row-start-1 flex min-w-0 items-center gap-1.5">
        <span className="min-w-[9ch] truncate text-sm font-semibold">{tx.merchant}</span>
        {/* Las insignias ceden espacio antes que el nombre: cada una se corta con "…". */}
        <span className="flex min-w-0 shrink items-center gap-1.5 overflow-hidden">
          <Badges tx={tx} />
        </span>
      </span>
      <span
        className={cn(
          'col-start-1 row-start-2 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground @xl:hidden',
          !amount.original && 'col-span-2',
        )}
      >
        <Swatch color={color} />
        <span className="truncate">{tx.category} ·</span>
        {/* La cuenta cede espacio antes que la categoría. */}
        <span className="flex min-w-0 shrink-4">
          <AccountLabel label={tx.account_label} />
        </span>
      </span>
      <span className="hidden min-w-0 items-center gap-2 text-[13px] text-ink-2 @xl:col-start-2 @xl:row-start-1 @xl:flex">
        <Swatch color={color} />
        <span className="truncate">{tx.category}</span>
      </span>
      <span className="hidden min-w-0 text-[13px] text-muted-foreground @xl:col-start-3 @xl:row-start-1 @xl:flex">
        <AccountLabel label={tx.account_label} />
      </span>
      {amount.original && (
        // Angosto: debajo del monto, a la derecha. Desde @xl va en la misma línea (abajo).
        <span className="col-start-2 row-start-2 justify-self-end text-xs text-muted-foreground tabular-nums @xl:hidden">
          {amount.original}
        </span>
      )}
      <span className="col-start-2 row-start-1 flex items-baseline justify-self-end gap-2 whitespace-nowrap tabular-nums @xl:col-start-4">
        {amount.original && (
          <span className="hidden text-xs text-muted-foreground @xl:inline">{amount.original}</span>
        )}
        <span className={cn('text-sm font-semibold', AMOUNT_TONE_CLASS[amountTone(tx)])}>
          {amount.main}
        </span>
      </span>
    </>
  )
}

/** Tipo, gasto único y corrección como etiquetas pequeñas junto al nombre. */
function Badges({ tx }: { tx: Tx }) {
  const links = linkBadges(tx)
  // Un vínculo (reembolso, cambio) dice más que el tipo: el tipo se omite.
  const kind = links.length && tx.link !== 'shared' ? null : kindBadge(tx)
  const oneOff = oneOffBadge(tx)
  return (
    <>
      {kind && (
        <Badge
          className={kind === 'Ingreso' ? 'bg-down-soft text-down' : 'bg-muted text-muted-foreground'}
        >
          {kind}
        </Badge>
      )}
      {oneOff === 'Único' && <Badge className="bg-up-soft text-up-ink">Único</Badge>}
      {oneOff === '¿Único?' && (
        <Badge className="border border-dashed border-up/40 bg-card text-up-ink">¿Único?</Badge>
      )}
      {tx.corrected && <Badge className="bg-secondary text-secondary-foreground">Corregida</Badge>}
      {links.map((badge) => (
        <Badge key={badge.label} className={LINK_TONE[badge.tone]}>
          {badge.label}
        </Badge>
      ))}
      {tx.note && (
        <span role="img" aria-label="Tiene nota" title={tx.note} className="shrink-0 text-muted-foreground">
          <StickyNote size={13} aria-hidden="true" />
        </span>
      )}
    </>
  )
}

const LINK_TONE: Record<LinkBadge['tone'], string> = {
  shared: 'bg-[#EEF3FB] text-[#2F4F7F]',
  linked: 'bg-muted text-muted-foreground',
  suggested: 'border border-dashed border-primary/40 bg-card text-primary',
}

/** Cuenta con los últimos dígitos siempre visibles: solo el nombre se trunca. Una cuenta
 * bancaria va con su nombre corto ("Ahorro ···0300"); el completo queda en `title`. */
function AccountLabel({ label }: { label: string }) {
  const { name, tail } = splitLabel(shortAccountLabel(label))
  return (
    <span className="flex min-w-0 gap-1" title={label}>
      <span className="truncate">{name}</span>
      {tail && <span className="shrink-0">{tail}</span>}
    </span>
  )
}

function Swatch({ color }: { color: string }) {
  return (
    <span
      aria-hidden="true"
      className="size-2 shrink-0 rounded-[3px]"
      style={{ background: color }}
    />
  )
}

interface BadgeProps {
  className: string
  children: string
}

/** Etiqueta que, si no cabe, se corta con "…" (el texto completo queda en `title`). */
function Badge({ className, children }: BadgeProps) {
  return (
    <span
      title={children}
      className={cn(
        'max-w-full min-w-[3ch] truncate rounded-full px-1.5 text-[10.5px] leading-[18px] font-semibold',
        className,
      )}
    >
      {children}
    </span>
  )
}
