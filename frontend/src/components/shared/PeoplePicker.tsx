import { Landmark, Plus, UserRound, X } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { FIELD } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import { type ChosenPerson, chosenOf, peopleOptions, type PeopleOption } from '@/lib/ledger'
import { fold } from '@/lib/picker'
import { useContacts } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { CHIP, CHIP_ON } from './styles'

interface PeoplePickerProps {
  chosen: readonly ChosenPerson[]
  onChange: (chosen: ChosenPerson[]) => void
  /** Contacts already in the group (they are not offered). */
  exclude?: readonly number[]
  /** Show the fixed "You" chip (a new group). */
  withMe?: boolean
}

/** People as chips with an autocomplete under the field, in this order: contacts (by name or
 * alias), names seen in the transfers ("seen in your bank") and "Create 'Ana'". */
export function PeoplePicker({ chosen, onChange, exclude = [], withMe = true }: PeoplePickerProps) {
  const ids = useId()
  const [query, setQuery] = useState('')
  const contacts = useContacts()
  const takenIds = new Set([
    ...exclude,
    ...chosen.flatMap((c) => (c.person.contact_id != null ? [c.person.contact_id] : [])),
  ])
  const takenNames = new Set(chosen.filter((c) => c.person.contact_id == null).map((c) => fold(c.label)))
  const options = peopleOptions(
    query,
    contacts.data?.contacts ?? [],
    contacts.data?.bank_names ?? [],
    takenIds,
    takenNames,
  )

  function pick(option: PeopleOption) {
    onChange([...chosen, chosenOf(option)])
    setQuery('')
    document.getElementById(`${ids}-input`)?.focus()
  }

  return (
    <div className="flex flex-col gap-2">
      <ul aria-label={t('shared.newGroup.people')} className="flex flex-wrap gap-2">
        {withMe && (
          <li>
            <span
              title={t('shared.people.youFixed')}
              className={cn(CHIP, CHIP_ON, 'cursor-default')}
            >
              {t('shared.you')}
            </span>
          </li>
        )}
        {chosen.map((person) => (
          <li key={person.key}>
            <span className={cn(CHIP, CHIP_ON, 'pr-1')}>
              <span className="truncate">{person.label}</span>
              <button
                type="button"
                aria-label={t('shared.people.remove', { name: person.label })}
                onClick={() => onChange(chosen.filter((c) => c.key !== person.key))}
                className={cn(
                  '-my-px flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-card/70',
                  FOCUS,
                )}
              >
                <X size={16} aria-hidden="true" />
              </button>
            </span>
          </li>
        ))}
      </ul>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2" htmlFor={`${ids}-input`}>
        {t('shared.newGroup.search')}
      </label>
      <input
        id={`${ids}-input`}
        value={query}
        maxLength={80}
        autoComplete="off"
        placeholder={t('shared.newGroup.searchPlaceholder')}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && options.length > 0) {
            event.preventDefault()
            pick(options[0])
          }
        }}
        className={FIELD}
      />
      {options.length > 0 && (
        <ul
          aria-label={t('shared.people.suggestions')}
          className="flex flex-col overflow-hidden rounded-xl border border-border bg-card"
        >
          {options.map((option) => (
            <li key={chosenOf(option).key + option.kind} className="border-b border-border last:border-b-0">
              <OptionButton option={option} onPick={() => pick(option)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function OptionButton({ option, onPick }: { option: PeopleOption; onPick: () => void }) {
  const base = cn(
    'flex min-h-12 w-full items-center gap-3 px-3.5 text-left text-sm hover:bg-muted/60',
    FOCUS,
    'focus-visible:ring-inset',
  )
  if (option.kind === 'contact') {
    return (
      <button type="button" onClick={onPick} className={base}>
        <UserRound size={18} aria-hidden="true" className="shrink-0 text-muted-foreground" />
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-semibold">{option.contact.name}</span>
          {option.alias && (
            <span className="truncate text-[13px] text-muted-foreground">
              {t('shared.people.alsoKnown', { alias: option.alias })}
            </span>
          )}
        </span>
      </button>
    )
  }
  if (option.kind === 'bank') {
    return (
      <button type="button" onClick={onPick} className={base}>
        <Landmark size={18} aria-hidden="true" className="shrink-0 text-muted-foreground" />
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-semibold">{option.bank.name}</span>
          <span className="truncate text-[13px] text-muted-foreground">
            {t('shared.people.seenInBank')}
          </span>
        </span>
      </button>
    )
  }
  return (
    <button type="button" onClick={onPick} className={base}>
      <Plus size={18} aria-hidden="true" className="shrink-0 text-primary" />
      <span className="truncate font-semibold text-primary">
        {t('shared.people.createNamed', { name: option.name })}
      </span>
    </button>
  )
}
