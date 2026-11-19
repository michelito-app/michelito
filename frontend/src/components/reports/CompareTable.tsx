import { Link } from 'react-router'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import type { Selection } from '@/lib/accountFilter'
import type { CompareCell, CompareRow, Comparison, MonthOption } from '@/lib/api'
import { BUILTIN, builtinName, THIRD_PARTY } from '@/lib/categories'
import { FLOW_COLORS } from '@/lib/colors'
import { formatPesos } from '@/lib/money'
import { useCategories } from '@/lib/queries'
import { cellClass, cellHref, cellTitle, type Range } from '@/lib/reports'
import { cn } from '@/lib/utils'

const ACCENTS: Record<string, string> = {
  ingresos: FLOW_COLORS.income.strong,
  gastos: FLOW_COLORS.expense.strong,
  terceros: FLOW_COLORS.transfer.strong,
}

const STICKY = 'sticky left-0 z-10 bg-card'
const HEAD = 'px-3 py-2 text-right text-xs font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase'

interface CompareTableProps {
  data: Comparison
  /** Meses con datos, del más nuevo al más viejo (para elegir el rango). */
  options: MonthOption[]
  range: Range
  onRange: (range: Range) => void
  selection: Selection
}

function MonthSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: MonthOption[]
  onChange: (month: string) => void
}) {
  return (
    <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cn('h-9 rounded-lg border border-border bg-card px-2 text-sm text-foreground', FOCUS)}
      >
        {options.map((o) => (
          <option key={o.month} value={o.month}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Comparar meses: ingresos, gastos, terceros y lo que quedó arriba; las categorías de gasto
 * debajo y, al final, los ingresos por categoría («Cripto» aparte de «Otros ingresos»). Una
 * celda que se aparta de lo habitual de su categoría se destaca (subida en terracota, más
 * intensa cuanto más sube; bajada con borde verde). Cada celda abre sus movimientos en
 * Transacciones. La tabla se desplaza a lo ancho dentro de su caja. */
export function CompareTable({ data, options, range, onRange, selection }: CompareTableProps) {
  const categories = useCategories()
  const thirdParty = builtinName(categories.data ?? [], BUILTIN.thirdParty, THIRD_PARTY)
  const first = data.months[0]?.month ?? ''
  const last = data.months[data.months.length - 1]?.month ?? ''
  return (
    <section aria-labelledby="compare-title" className={cn(PANEL, 'flex min-w-0 flex-col gap-3 py-5')}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-6">
        <h2 id="compare-title" className={PANEL_TITLE}>
          Comparar meses
        </h2>
        {options.length > 1 && (
          <div className="flex flex-wrap items-center gap-3">
            <MonthSelect label="Desde" value={first} options={options} onChange={(m) => onRange({ ...range, from: m, to: range.to ?? last })} />
            <MonthSelect label="Hasta" value={last} options={options} onChange={(m) => onRange({ ...range, from: range.from ?? first, to: m })} />
          </div>
        )}
      </div>
      <p className="px-6 text-[13px] text-muted-foreground">
        RD$ por mes. Destacado: se aparta de lo habitual de su fila más de 30 % y de RD$ 1,000
        (terracota si subió, borde verde si bajó). Los meses en curso no se comparan.
      </p>
      <div className="max-w-full overflow-x-auto" tabIndex={0} aria-label="Tabla de meses (se desplaza a lo ancho)">
        <table className="w-max min-w-full border-collapse text-sm tabular-nums">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={cn(HEAD, STICKY, 'pl-6 text-left')}>
                Fila
              </th>
              {data.months.map((m) => (
                <th key={m.month} scope="col" className={HEAD}>
                  {m.label.replace(/ (\d{4})$/, (_, y: string) => ` ${y.slice(2)}`)}
                  {m.partial && <span className="font-normal normal-case"> · en curso</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.totals.map((row) => (
              <Line key={row.key} row={row} months={data.months} selection={selection} thirdParty={thirdParty} strong />
            ))}
            {data.categories.map((row) => (
              <Line key={row.key} row={row} months={data.months} selection={selection} thirdParty={thirdParty} />
            ))}
            {(data.incomes ?? []).length > 0 && (
              <tr className="border-b border-border">
                <td colSpan={data.months.length + 1} className={cn(HEAD, 'pt-4 pl-6 text-left')}>
                  Ingresos por categoría
                </td>
              </tr>
            )}
            {(data.incomes ?? []).map((row) => (
              <Line key={row.key} row={row} months={data.months} selection={selection} thirdParty={thirdParty} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

interface LineProps {
  row: CompareRow
  months: MonthOption[]
  selection: Selection
  thirdParty: string
  strong?: boolean
}

function Line({ row, months, selection, thirdParty, strong = false }: LineProps) {
  const accent = ACCENTS[row.key]
  return (
    <tr className={cn('border-b border-[#F2F2EE]', row.key === 'neto' && 'border-b-border')}>
      <th scope="row" className={cn(STICKY, 'max-w-[180px] truncate py-2 pr-3 pl-6 text-left', strong ? 'font-semibold' : 'font-medium')} title={row.label}>
        <span className="flex items-center gap-1.5">
          {accent && <span aria-hidden="true" className="size-2 shrink-0 rounded-[3px]" style={{ background: accent }} />}
          <span className="truncate">{row.label}</span>
        </span>
      </th>
      {row.cells.map((cell, index) => (
        <ValueCell
          key={months[index].month}
          cell={cell}
          rowKey={row.key}
          label={row.label}
          month={months[index]}
          href={cellHref(row.key, months[index].month, selection, thirdParty)}
        />
      ))}
    </tr>
  )
}

function ValueCell({
  cell,
  rowKey,
  label,
  month,
  href,
}: {
  cell: CompareCell
  rowKey: string
  label: string
  month: MonthOption
  href: string | null
}) {
  const text = formatPesos(cell.amount_cents)
  const title = cellTitle(cell)
  const body = href ? (
    <Link
      to={href}
      aria-label={`${label}, ${month.label}: RD$ ${text}. ${title}`}
      className={cn(
        'block rounded-md px-3 py-2 no-underline hover:underline',
        month.partial ? 'text-muted-foreground' : 'text-foreground',
        FOCUS,
      )}
    >
      {text}
    </Link>
  ) : (
    <span className="block px-3 py-2">{text}</span>
  )
  return (
    <td title={title} className={cn('p-0.5 text-right whitespace-nowrap', month.partial && 'text-muted-foreground')}>
      <div className={cn('rounded-md', cellClass(rowKey, cell))}>{body}</div>
    </td>
  )
}
