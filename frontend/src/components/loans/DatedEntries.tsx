import { useState } from 'react'
import { Field, FormAlert } from '@/components/installments/formParts'
import { Action, FIELD, Failure } from '@/components/transactions/linkParts'
import { localToday } from '@/lib/months'
import { cn } from '@/lib/utils'
import { SectionTitle } from './parts'

export interface DatedEntry {
  day: string
  text: string // the value, formatted
  note: string // "since 15 Jan 2026"
  removeLabel: string | null // null: it cannot be removed
}

interface DatedEntriesProps {
  testId: string
  title: string
  hint?: string
  entries: readonly DatedEntry[]
  labels: { add: string; day: string; value: string; save: string; invalid: string; remove: string }
  /** The typed value, or null when it is not valid. */
  parse: (text: string) => number | null
  busy: boolean
  error: Error | null
  onSave: (day: string, value: number, done: () => void) => void
  onRemove: (day: string) => void
}

/** A dated list of a loan (rates, real balances): each entry with "Remove", and a short form
 * to add one from a day on. */
export function DatedEntries({
  testId,
  title,
  hint,
  entries,
  labels,
  parse,
  busy,
  error,
  onSave,
  onRemove,
}: DatedEntriesProps) {
  const [adding, setAdding] = useState(false)
  const [day, setDay] = useState(localToday)
  const [text, setText] = useState('')
  const [invalid, setInvalid] = useState(false)

  function save() {
    const value = parse(text)
    if (value === null || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return setInvalid(true)
    onSave(day, value, () => {
      setAdding(false)
      setText('')
    })
  }

  return (
    <section data-testid={testId} className="flex flex-col gap-2">
      <SectionTitle>{title}</SectionTitle>
      {hint && <p className="text-[13px] text-muted-foreground">{hint}</p>}
      {entries.length > 0 && (
        <ul className="flex flex-col divide-y divide-border rounded-xl border border-border">
          {entries.map((entry) => (
            <li key={entry.day} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span className="flex min-w-0 flex-col">
                <span className="text-sm font-semibold tabular-nums">{entry.text}</span>
                <span className="text-xs text-muted-foreground">{entry.note}</span>
              </span>
              {entry.removeLabel !== null && (
                <Action label={entry.removeLabel} disabled={busy} onClick={() => onRemove(entry.day)}>
                  {labels.remove}
                </Action>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <form
          className="flex flex-col gap-3 rounded-xl border border-border px-3 py-3"
          onSubmit={(event) => {
            event.preventDefault()
            save()
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={labels.day}>
              <input
                type="date"
                value={day}
                onChange={(event) => {
                  setDay(event.target.value)
                  setInvalid(false)
                }}
                className={FIELD}
              />
            </Field>
            <Field label={labels.value}>
              <input
                value={text}
                inputMode="decimal"
                onChange={(event) => {
                  setText(event.target.value)
                  setInvalid(false)
                }}
                className={cn(FIELD, 'tabular-nums')}
              />
            </Field>
          </div>
          {invalid && <FormAlert>{labels.invalid}</FormAlert>}
          <div>
            <Action primary disabled={busy} onClick={save}>
              {labels.save}
            </Action>
          </div>
        </form>
      ) : (
        <div>
          <Action onClick={() => setAdding(true)}>{labels.add}</Action>
        </div>
      )}
      <Failure error={error} />
    </section>
  )
}
