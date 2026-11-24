import { useMemo, useState } from 'react'
import { SheetOrInline } from '@/components/ui/sheet-or-inline'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { useCategories } from '@/lib/queries'
import { formatDop } from '@/lib/money'
import { shortDay } from '@/lib/months'
import { useTagCandidates, useTagTransactions } from '@/lib/tagQueries'
import { type CandidateFilters, type TagCandidate, pickerSections, selectionSummary, visibleSelection } from '@/lib/tags'

interface AddTransactionsProps {
  tagId: number
  onClose: () => void
}

/** "Add transactions": a date range and a merchant filter, the likely rows first, and one
 * button that tags every checked row (one log entry). */
export function AddTransactions({ tagId, onClose }: AddTransactionsProps) {
  const [filters, setFilters] = useState<CandidateFilters>({})
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const candidates = useTagCandidates(tagId, filters)
  const categories = useCategories()
  const tag = useTagTransactions()
  const items = useMemo(() => candidates.data?.items ?? [], [candidates.data])
  const sections = useMemo(() => pickerSections(items), [items])
  const shown = visibleSelection(selected, items)
  const chosen = selectionSummary(items, shown)

  const toggle = (fingerprint: string, on: boolean) => {
    const next = new Set(selected)
    if (on) next.add(fingerprint)
    else next.delete(fingerprint)
    setSelected(next)
  }
  const submit = () =>
    tag.mutate({ id: tagId, fingerprints: [...shown] }, { onSuccess: () => onClose() })

  return (
    <SheetOrInline title={t('tags.picker.title')} onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          <DateField
            label={t('tags.picker.from')}
            value={filters.from ?? candidates.data?.from ?? ''}
            onChange={(from) => setFilters({ ...filters, from })}
          />
          <DateField
            label={t('tags.picker.to')}
            value={filters.to ?? candidates.data?.to ?? ''}
            onChange={(to) => setFilters({ ...filters, to })}
          />
          <label className="flex min-w-[160px] flex-col gap-1 text-[12px] font-medium">
            {t('tags.picker.category')}
            <select
              value={filters.category_id ?? ''}
              onChange={(event) =>
                setFilters({
                  ...filters,
                  category_id: event.target.value === '' ? undefined : Number(event.target.value),
                })
              }
              className="h-10 rounded-lg border border-input bg-transparent px-2 text-sm"
            >
              <option value="">{t('tags.picker.anyCategory')}</option>
              {(categories.data ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-[160px] flex-1 flex-col gap-1 text-[12px] font-medium">
            {t('tags.picker.merchant')}
            <Input
              value={filters.merchant ?? ''}
              onChange={(event) => setFilters({ ...filters, merchant: event.target.value })}
              className="h-10"
            />
          </label>
        </div>
        {candidates.isPending ? (
          <Skeleton className="h-40 rounded-xl" />
        ) : items.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t('tags.picker.none')}</p>
        ) : (
          <>
            <Rows title={t('tags.picker.likely')} rows={sections.likely} selected={selected} onToggle={toggle} />
            <Rows title={t('tags.picker.rest')} rows={sections.rest} selected={selected} onToggle={toggle} />
          </>
        )}
        {tag.error && (
          <p role="alert" className="text-[13px] text-destructive">
            {tag.error.message}
          </p>
        )}
        <Button
          type="button"
          disabled={chosen.count === 0 || tag.isPending}
          onClick={submit}
          className="sticky bottom-0 h-11 rounded-xl"
        >
          {t('tags.picker.submit', { count: chosen.count, amount: formatDop(chosen.totalDopCents) })}
        </Button>
      </div>
    </SheetOrInline>
  )
}

interface DateFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
}

function DateField({ label, value, onChange }: DateFieldProps) {
  return (
    <label className="flex flex-col gap-1 text-[12px] font-medium">
      {label}
      <Input type="date" value={value} onChange={(event) => onChange(event.target.value)} className="h-10" />
    </label>
  )
}

interface RowsProps {
  title: string
  rows: TagCandidate[]
  selected: ReadonlySet<string>
  onToggle: (fingerprint: string, on: boolean) => void
}

function Rows({ title, rows, selected, onToggle }: RowsProps) {
  if (rows.length === 0) return null
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h3 className="text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      <ul className="flex flex-col">
        {rows.map((row) => (
          <li key={row.fingerprint}>
            <label className="flex min-h-11 items-center gap-3 border-b border-border/60 py-2 text-[13px]">
              <Checkbox
                checked={row.tagged || selected.has(row.fingerprint)}
                disabled={row.tagged}
                onCheckedChange={(on) => onToggle(row.fingerprint, on === true)}
                aria-label={row.description}
              />
              <span className="w-14 shrink-0 text-muted-foreground tabular-nums">{shortDay(row.day)}</span>
              <span className="min-w-0 flex-1 truncate">{row.description}</span>
              <span className="hidden text-muted-foreground sm:inline">{row.category}</span>
              <span className="tabular-nums">
                {row.tagged
                  ? t('tags.picker.already')
                  : row.amount_dop_cents === null
                    ? ''
                    : formatDop(row.amount_dop_cents)}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  )
}
