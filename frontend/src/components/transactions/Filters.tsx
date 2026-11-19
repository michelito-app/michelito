import { Search, SlidersHorizontal, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { t } from '@/i18n'
import type { Category } from '@/lib/api'
import { categoryGroups, NEW_CATEGORY, NEW_CATEGORY_ACTION } from '@/lib/categories'
import {
  activeFilterCount,
  GROUP_OPTIONS,
  KIND_OPTIONS,
  SORT_OPTIONS,
  type TxFilters,
} from '@/lib/transactions'
import { cn } from '@/lib/utils'
import { FOCUS } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'

/** Wait after the last key press before searching. */
const SEARCH_DEBOUNCE_MS = 250
const ALL = ''

const FIELD =
  'flex h-11 min-w-0 max-w-full items-center rounded-xl border border-border bg-card transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30'

interface FiltersProps {
  filters: TxFilters
  categories: Category[]
  /** Changes kind, category, grouping or sort (adds a history entry). The month and the accounts
   * are chosen in the header. */
  onChange: (patch: Partial<TxFilters>) => void
  /** Search, already debounced (replaces the history entry). */
  onSearch: (q: string) => void
  /** At the end of the row (the select button). */
  children?: ReactNode
  /** Phone: the search stays visible; the rest goes into a sheet behind "Filters (N)". */
  mobile?: boolean
}

/** Search, filters, grouping and sort of the list; all of it lives in the URL. */
export function Filters({
  filters,
  categories,
  onChange,
  onSearch,
  children,
  mobile = false,
}: FiltersProps) {
  if (mobile) {
    return (
      <MobileFilters filters={filters} categories={categories} onChange={onChange} onSearch={onSearch}>
        {children}
      </MobileFilters>
    )
  }
  return (
    <div role="search" className="flex flex-wrap items-center gap-2.5">
      <SearchField q={filters.q} onSearch={onSearch} />
      <FilterFields filters={filters} categories={categories} onChange={onChange} />
      {children}
    </div>
  )
}

/** The phone's row: search, the button that opens the filter sheet and the select button. */
function MobileFilters({ filters, categories, onChange, onSearch, children }: FiltersProps) {
  const [open, setOpen] = useState(false)
  const count = activeFilterCount(filters)
  return (
    <div role="search" className="flex items-center gap-2">
      <SearchField q={filters.q} onSearch={onSearch} />
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className={cn(
          'flex h-11 shrink-0 items-center gap-1.5 rounded-xl border px-3 text-sm font-semibold',
          count > 0
            ? 'border-primary/40 bg-secondary text-secondary-foreground'
            : 'border-border bg-card text-foreground',
          FOCUS,
        )}
      >
        <SlidersHorizontal size={16} aria-hidden="true" />
        {t('transactions.filters.open', { count })}
      </button>
      {children}
      {open && (
        <BottomSheet title={t('transactions.filters.title')} onClose={() => setOpen(false)}>
          <div className="flex flex-col gap-2.5 [&>label]:w-full">
            <FilterFields filters={filters} categories={categories} onChange={onChange} />
          </div>
          <Button className="h-11 rounded-xl text-sm font-semibold" onClick={() => setOpen(false)}>
            {t('transactions.filters.done')}
          </Button>
        </BottomSheet>
      )}
    </div>
  )
}

type FilterFieldsProps = Pick<FiltersProps, 'filters' | 'categories' | 'onChange'>

/** Kind, category, grouping, sort and the shared filter (when set). */
function FilterFields({ filters, categories, onChange }: FilterFieldsProps) {
  return (
    <>
      <SelectField
        label={t('transactions.filters.kind')}
        value={filters.kind ?? ALL}
        onChange={(value) =>
          onChange({ kind: KIND_OPTIONS.find((o) => o.kind === value)?.kind ?? null })
        }
      >
        <option value={ALL}>{t('transactions.filters.allKinds')}</option>
        {KIND_OPTIONS.map((o) => (
          <option key={o.kind} value={o.kind}>
            {o.label}
          </option>
        ))}
      </SelectField>
      <SelectField
        label={t('transactions.filters.category')}
        value={filters.category ?? ALL}
        onChange={(value) => onChange({ category: value || null })}
      >
        <option value={ALL}>{t('transactions.filters.allCategories')}</option>
        <CategoryOptions categories={categories} current={filters.category} />
      </SelectField>
      <SelectField
        label={t('transactions.filters.groupBy')}
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
        label={t('transactions.filters.sort')}
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
          aria-label={t('transactions.filters.removeShared')}
          className={cn(
            'flex h-11 items-center gap-1.5 rounded-xl border border-primary/40 bg-[#F6FAF8] px-3 text-sm font-semibold text-primary',
            FOCUS,
          )}
        >
          {t('transactions.filters.sharedPending')}
          <X size={14} aria-hidden="true" />
        </button>
      )}
    </>
  )
}

interface CategoryOptionsProps {
  categories: readonly Category[]
  current: string | null
  /** Adds a "new category" option at the end (value `NEW_CATEGORY`). */
  allowNew?: boolean
}

/** Categories in an `<optgroup>` per kind, without the hidden ones (except the current one); if
 * the current one is missing (or they are still loading), it goes first. */
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
          {t('transactions.filters.newCategory')}
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
  // If the URL changes from outside (clear filters, see the whole merchant), the field follows it.
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
      <span className="sr-only">{t('transactions.filters.search')}</span>
      <input
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onSearch(text.trim())
        }}
        placeholder={t('transactions.filters.searchPlaceholder')}
        className="h-full min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
      />
      {text !== '' && (
        <button
          type="button"
          aria-label={t('transactions.filters.clearSearch')}
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
