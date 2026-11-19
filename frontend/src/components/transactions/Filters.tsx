import { Search, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import type { Category } from '@/lib/api'
import { categoryGroups, NEW_CATEGORY, NEW_CATEGORY_ACTION } from '@/lib/categories'
import { GROUP_OPTIONS, KIND_OPTIONS, SORT_OPTIONS, type TxFilters } from '@/lib/transactions'
import { cn } from '@/lib/utils'
import { FOCUS } from '@/components/summary/styles'

/** Espera tras la última tecla antes de buscar. */
const SEARCH_DEBOUNCE_MS = 250
const ALL = ''

const FIELD =
  'flex h-11 min-w-0 max-w-full items-center rounded-xl border border-border bg-card transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30'

interface FiltersProps {
  filters: TxFilters
  categories: Category[]
  /** Cambia tipo, categoría, agrupación u orden (deja una entrada en el historial). El mes y
   * las cuentas se eligen en la cabecera. */
  onChange: (patch: Partial<TxFilters>) => void
  /** Búsqueda ya con debounce (reemplaza la entrada del historial). */
  onSearch: (q: string) => void
  /** Al final de la fila (el botón «Seleccionar»). */
  children?: ReactNode
}

/** Búsqueda, filtros, agrupación y orden de la lista; todo vive en la URL. */
export function Filters({ filters, categories, onChange, onSearch, children }: FiltersProps) {
  return (
    <div role="search" className="flex flex-wrap items-center gap-2.5">
      <SearchField q={filters.q} onSearch={onSearch} />
      <SelectField
        label="Tipo"
        value={filters.kind ?? ALL}
        onChange={(value) =>
          onChange({ kind: KIND_OPTIONS.find((o) => o.kind === value)?.kind ?? null })
        }
      >
        <option value={ALL}>Todos</option>
        {KIND_OPTIONS.map((o) => (
          <option key={o.kind} value={o.kind}>
            {o.label}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="Categoría"
        value={filters.category ?? ALL}
        onChange={(value) => onChange({ category: value || null })}
      >
        <option value={ALL}>Todas</option>
        <CategoryOptions categories={categories} current={filters.category} />
      </SelectField>
      <SelectField
        label="Agrupar por"
        value={filters.group}
        onChange={(value) =>
          onChange({ group: GROUP_OPTIONS.find((o) => o.group === value)?.group ?? 'day' })
        }
      >
        {GROUP_OPTIONS.map((o) => (
          <option key={o.group} value={o.group}>
            {o.label}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="Ordenar"
        value={filters.sort}
        onChange={(value) =>
          onChange({ sort: SORT_OPTIONS.find((o) => o.sort === value)?.sort ?? 'date' })
        }
      >
        {SORT_OPTIONS.map((o) => (
          <option key={o.sort} value={o.sort}>
            {o.label}
          </option>
        ))}
      </SelectField>
      {filters.shared === 'pending' && (
        <button
          type="button"
          onClick={() => onChange({ shared: null })}
          aria-label="Quitar el filtro de compartidos con pendiente"
          className={cn(
            'flex h-11 items-center gap-1.5 rounded-xl border border-primary/40 bg-[#F6FAF8] px-3 text-sm font-semibold text-primary',
            FOCUS,
          )}
        >
          Compartidos con pendiente
          <X size={14} aria-hidden="true" />
        </button>
      )}
      {children}
    </div>
  )
}

interface CategoryOptionsProps {
  categories: readonly Category[]
  current: string | null
  /** Agrega al final "+ Nueva categoría…" (valor `NEW_CATEGORY`). */
  allowNew?: boolean
}

/** Categorías en `<optgroup>` por tipo, sin las ocultas (salvo la actual); si la actual no
 * está (o aún cargan), va al principio. */
export function CategoryOptions({ categories, current, allowNew = false }: CategoryOptionsProps) {
  const known = current === null || categories.some((c) => c.name === current)
  return (
    <>
      {!known && <option value={current}>{current}</option>}
      {categoryGroups(categories, current).map((group) => (
        <optgroup key={group.label} label={group.label}>
          {group.names.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </optgroup>
      ))}
      {allowNew && (
        <option value={NEW_CATEGORY} data-action={NEW_CATEGORY_ACTION}>
          + Nueva categoría…
        </option>
      )}
    </>
  )
}

interface SearchFieldProps {
  q: string
  onSearch: (q: string) => void
}

function SearchField({ q, onSearch }: SearchFieldProps) {
  const [text, setText] = useState(q)
  const [synced, setSynced] = useState(q)
  // Si la URL cambia por fuera (Quitar filtros, Ver todo el comercio), el campo la sigue.
  if (q !== synced) {
    setSynced(q)
    if (q !== text.trim()) setText(q)
  }

  useEffect(() => {
    if (text.trim() === q) return
    const timer = setTimeout(() => onSearch(text.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [text, q, onSearch])

  return (
    <label className={cn(FIELD, 'flex-[1_1_260px] gap-2 px-3.5 text-muted-foreground')}>
      <Search size={16} aria-hidden="true" className="shrink-0" />
      <span className="sr-only">Buscar</span>
      <input
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onSearch(text.trim())
        }}
        placeholder="Buscar comercio o descripción"
        className="h-full min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
      />
      {text !== '' && (
        <button
          type="button"
          aria-label="Borrar búsqueda"
          onClick={() => {
            setText('')
            onSearch('')
          }}
          className={cn(
            '-mr-2 flex size-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground',
            FOCUS,
          )}
        >
          <X size={16} aria-hidden="true" />
        </button>
      )}
    </label>
  )
}

interface SelectFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}

function SelectField({ label, value, onChange, children }: SelectFieldProps) {
  return (
    <label className={cn(FIELD, 'flex-[1_1_auto] gap-1.5 pl-3 text-[13px] text-muted-foreground sm:flex-none')}>
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-full max-w-full min-w-0 flex-1 cursor-pointer truncate bg-transparent pr-2 text-sm font-semibold text-foreground outline-none sm:max-w-[240px]"
      >
        {children}
      </select>
    </label>
  )
}
