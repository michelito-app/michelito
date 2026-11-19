import { useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { LogEntryRow } from '@/components/log/LogEntryRow'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import {
  type Author,
  groupBySession,
  KIND_LABELS,
  kindLabel,
  type LogFilters,
  NO_FILTERS,
  PAGE_SIZE,
} from '@/lib/log'
import { useLog } from '@/lib/logQueries'
import { cn } from '@/lib/utils'

const FIELD =
  'h-11 min-w-0 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30'

/** Bitácora: lo cambiado desde el board, por sesión de edición, con motivo y «Deshacer». */
export function LogPage() {
  const [filters, setFilters] = useState<LogFilters>(NO_FILTERS)
  const [limit, setLimit] = useState(PAGE_SIZE)
  const log = useLog(filters, limit)
  const update = (patch: Partial<LogFilters>) => {
    setFilters((current) => ({ ...current, ...patch }))
    setLimit(PAGE_SIZE)
  }
  const filtered = filters.kind !== null || filters.author !== null || filters.q.trim() !== ''
  const kinds = [...new Set([...Object.keys(KIND_LABELS), ...(log.data?.kinds ?? [])])]

  return (
    <>
      <header className="flex flex-col gap-1.5">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Bitácora</h1>
        <p className="text-[13px] text-muted-foreground">
          Lo que cambiaste (tú o Claude), para repasarlo y deshacerlo
        </p>
      </header>
      <div className="flex max-w-[960px] min-w-0 flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Tipo de cambio"
            value={filters.kind ?? ''}
            onChange={(event) => update({ kind: event.target.value || null })}
            className={cn(FIELD, 'flex-[1_1_160px] cursor-pointer')}
          >
            <option value="">Todos los tipos</option>
            {kinds.map((kind) => (
              <option key={kind} value={kind}>
                {kindLabel(kind)}
              </option>
            ))}
          </select>
          <select
            aria-label="Autor"
            value={filters.author ?? ''}
            onChange={(event) => update({ author: (event.target.value || null) as Author | null })}
            className={cn(FIELD, 'flex-[1_1_120px] cursor-pointer')}
          >
            <option value="">Tú y Claude</option>
            <option value="usuario">Tú</option>
            <option value="claude">Claude</option>
          </select>
          <input
            type="search"
            aria-label="Buscar en la bitácora"
            placeholder="Buscar comercio, valor o motivo"
            value={filters.q}
            onChange={(event) => update({ q: event.target.value })}
            className={cn(FIELD, 'flex-[2_1_200px]')}
          />
        </div>
        {log.isPending ? (
          <Skeleton className="h-48 rounded-2xl" />
        ) : log.isError ? (
          <LoadError what="la bitácora" error={log.error} onRetry={() => void log.refetch()} />
        ) : log.data.total === 0 ? (
          <Empty filtered={filtered} />
        ) : (
          <Sessions
            data={log.data}
            onMore={() => setLimit((current) => current + PAGE_SIZE)}
            loading={log.isFetching}
          />
        )}
      </div>
    </>
  )
}

function Empty({ filtered }: { filtered: boolean }) {
  return (
    <section className={cn(PANEL, 'flex flex-col gap-2 px-5 py-5 text-[13px] text-ink-2 sm:px-6')}>
      {filtered ? (
        <p>Nada con estos filtros.</p>
      ) : (
        <>
          <p className="text-sm font-semibold text-foreground">Todavía no hay cambios.</p>
          <p>
            Aquí quedará cada cambio que hagas en el board: categoría (solo esa transacción o
            todo el comercio), nota, gasto único, compartidos, cambios de divisas, inversiones,
            caja fuerte, recurrentes, lo revisado en «Para revisar», palabras clave y borrar o
            cambiar el tipo de una categoría. Cada uno con lo que había antes, lo que quedó y
            «Deshacer».
          </p>
          <p>No se registran el color, el nombre ni ocultar una categoría.</p>
        </>
      )}
    </section>
  )
}

interface SessionsProps {
  data: NonNullable<ReturnType<typeof useLog>['data']>
  onMore: () => void
  loading: boolean
}

function Sessions({ data, onMore, loading }: SessionsProps) {
  const groups = groupBySession(data.items)
  const left = data.total - data.items.length
  return (
    <div className="flex flex-col gap-4">
      {groups.map((group) => (
        <section
          key={group.key}
          aria-label={group.label}
          className={cn(PANEL, 'flex min-w-0 flex-col px-4 pt-4 pb-1 sm:px-6')}
        >
          <h2 className="text-[15px] font-[650] tracking-tight">{group.label}</h2>
          <ul className="flex flex-col">
            {group.entries.map((entry) => (
              <LogEntryRow key={entry.id} entry={entry} />
            ))}
          </ul>
        </section>
      ))}
      {left > 0 && (
        <button
          type="button"
          disabled={loading}
          onClick={onMore}
          className={cn(
            '-mx-2 flex min-h-11 items-center self-start rounded-md px-2 text-[13px] font-semibold text-primary hover:bg-muted/60',
            FOCUS,
          )}
        >
          Ver más ({left})
        </button>
      )}
    </div>
  )
}
