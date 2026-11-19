import { useState, type ReactNode } from 'react'
import { t } from '@/i18n'
import type { Candidate } from '@/lib/api'
import { shownCandidates } from '@/lib/picker'
import { Action, FIELD, LinkedRow, PickList } from './linkParts'

interface CandidatePickerProps {
  items: Candidate[]
  /** Name of the list (screen readers and the search box). */
  label: string
  /** With checkboxes: what is chosen and how it changes. */
  chosen?: ReadonlySet<string>
  onToggle?: (fingerprint: string) => void
  /** Without checkboxes: the action of each option (e.g. link). */
  action?: (item: Candidate) => ReactNode
}

/** Picker of a link: a search box (text or amount, over the whole list), the first options the
 * server marked and the rest behind a "see more (N)" button. */
export function CandidatePicker({ items, label, chosen, onToggle, action }: CandidatePickerProps) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(false)
  const { visible, more } = shownCandidates(items, query)
  const searching = query.trim() !== ''
  const shown = expanded ? [...visible, ...more] : visible

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <input
        type="search"
        aria-label={t('transactions.picker.searchIn', { label: label.toLowerCase() })}
        placeholder={t('transactions.picker.placeholder')}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className={FIELD}
      />
      {searching && visible.length === 0 && (
        <p className="text-[13px] text-muted-foreground">
          {t('transactions.picker.noMatch', { query: query.trim() })}
        </p>
      )}
      {!searching && visible.length === 0 && !expanded && (
        <p className="text-[13px] text-muted-foreground">
          {t('transactions.picker.noneFits')}
        </p>
      )}
      {shown.length > 0 &&
        (chosen && onToggle ? (
          <PickList items={shown} chosen={chosen} onToggle={onToggle} label={label} />
        ) : (
          <ul aria-label={label} className="flex flex-col gap-2">
            {shown.map((item) => (
              <LinkedRow key={item.fingerprint} item={item} action={action?.(item)} />
            ))}
          </ul>
        ))}
      {more.length > 0 && (
        <div>
          <Action onClick={() => setExpanded((v) => !v)}>
            {expanded
              ? t('transactions.picker.seeLess')
              : t('transactions.picker.seeMore', { count: more.length })}
          </Action>
        </div>
      )}
    </div>
  )
}
