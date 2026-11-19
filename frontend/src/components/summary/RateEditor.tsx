import { type FormEvent, useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { monthName } from '@/lib/months'
import { useSaveRate } from '@/lib/queries'
import { parseRate, rateText } from '@/lib/summary'

interface RateEditorProps {
  month: string
  current: string | null
  onClose: () => void
}

/** Campo inline para fijar a mano la tasa del mes (RD$ por US$). */
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
    ? 'Escribe un número mayor que cero, con hasta 4 decimales.'
    : save.isError
      ? `No se pudo guardar la tasa: ${save.error.message}`
      : null

  return (
    <form onSubmit={submit} className="flex flex-col gap-2" noValidate>
      <label htmlFor={id} className="text-[13px] text-ink-2">
        Tasa de {monthName(month)} (RD$ por US$)
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
          {save.isPending ? 'Guardando…' : 'Guardar'}
        </Button>
        <Button type="button" variant="ghost" className="h-11 px-3" onClick={onClose}>
          Cancelar
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
