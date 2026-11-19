import { type FormEvent, useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import { monthName } from '@/lib/months'
import { useSaveRate } from '@/lib/queries'
import { parseRate, rateText } from '@/lib/summary'

interface RateEditorProps {
  month: string
  current: string | null
  onClose: () => void
}

/** Inline field to set the month's rate by hand (RD$ per US$). */
export function RateEditor({ month, current, onClose }: RateEditorProps) {
  const id = useId()
  const [text, setText] = useState(current ? rateText(current) : '')
  const [invalid, setInvalid] = useState(false)
  const save = useSaveRate(month)

  function submit(event: FormEvent) {
    event.preventDefault()
    const value = parseRate(text)
    setInvalid(value === null)
    if (value !== null) save.mutate(value, { onSuccess: onClose })
  }

  const error = invalid
    ? t('summary.rateEditor.invalid')
    : save.isError
      ? t('summary.rateEditor.saveError', { message: save.error.message })
      : null

  return (
    <form onSubmit={submit} className="flex flex-col gap-2" noValidate>
      <label htmlFor={id} className="text-[13px] text-ink-2">
        {t('summary.rateEditor.label', { month: monthName(month) })}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={id}
          value={text}
          onChange={(e) => setText(e.target.value)}
          inputMode="decimal"
          autoComplete="off"
          autoFocus
          aria-invalid={error !== null}
          aria-describedby={error ? `${id}-error` : undefined}
          className="h-11 w-28 bg-card text-base tabular-nums"
        />
        <Button type="submit" className="h-11 px-4" disabled={save.isPending}>
          {save.isPending ? t('summary.rateEditor.saving') : t('common.save')}
        </Button>
        <Button type="button" variant="ghost" className="h-11 px-3" onClick={onClose}>
          {t('common.cancel')}
        </Button>
      </div>
      {error && (
        <p id={`${id}-error`} role="alert" className="text-[13px] text-up">
          {error}
        </p>
      )}
    </form>
  )
}
