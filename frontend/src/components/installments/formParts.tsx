import type { ReactNode } from 'react'
import { FIELD } from '@/components/transactions/linkParts'
import { COUNT_MAX, COUNT_MIN, NAME_MAX } from '@/lib/installments'
import { cn } from '@/lib/utils'

/** A labelled field of the installment forms. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
      {label}
      {children}
      {hint && <span className="text-xs font-normal text-muted-foreground">{hint}</span>}
    </label>
  )
}

interface NumberInputProps {
  value: string
  onChange: (value: string) => void
  min?: number
  max?: number
}

export function NumberInput({ value, onChange, min = COUNT_MIN, max = COUNT_MAX }: NumberInputProps) {
  return (
    <input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      step={1}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cn(FIELD, 'tabular-nums')}
    />
  )
}

/** The plan's name: prefilled, so it reads quieter than the fields the user fills. */
export function NameInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <input
      value={value}
      maxLength={NAME_MAX}
      onChange={(event) => onChange(event.target.value)}
      className={cn(FIELD, 'h-10 border-dashed text-[13px] text-ink-2')}
    />
  )
}

/** A message of the form: what to fix, or why saving failed. */
export function FormAlert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-[13px] text-up-ink">
      {children}
    </p>
  )
}
