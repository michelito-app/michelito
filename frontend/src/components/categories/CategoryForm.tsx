import { useId, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Kind } from '@/lib/api'
import { COLOR_CHOICES, GROUPS } from '@/lib/categories'
import { cn } from '@/lib/utils'

export interface CategoryFields {
  name: string
  kind: Kind
  color: string | null
}

interface CategoryFormProps {
  initial: CategoryFields
  /** A system category: its kind cannot change (logic depends on it). */
  kindLocked?: boolean
  submitLabel: string
  pending: boolean
  error: string | null
  onSubmit: (fields: CategoryFields) => void
  onCancel: () => void
}

export const FIELD_CLASS =
  'h-11 w-full rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm font-medium text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30'

/** Name, kind and colour of a category. */
export function CategoryForm({
  initial,
  kindLocked = false,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: CategoryFormProps) {
  const ids = useId()
  const [fields, setFields] = useState<CategoryFields>(initial)
  const blank = fields.name.trim() === ''

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!blank) onSubmit({ ...fields, name: fields.name.trim() })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        {t('categories.form.name')}
        <input
          autoFocus
          value={fields.name}
          maxLength={40}
          onChange={(event) => setFields({ ...fields, name: event.target.value })}
          className={FIELD_CLASS}
        />
      </label>
      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        {t('categories.form.kind')}
        <select
          value={fields.kind}
          disabled={kindLocked}
          onChange={(event) => setFields({ ...fields, kind: event.target.value as Kind })}
          className={cn(FIELD_CLASS, 'cursor-pointer disabled:cursor-not-allowed disabled:opacity-60')}
        >
          {GROUPS.map((group) => (
            <option key={group.kind} value={group.kind}>
              {group.singular}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="flex flex-col gap-2">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">{t('categories.form.color')}</legend>
        <div className="flex flex-wrap gap-2">
          <ColorChoice
            name={`${ids}-color`}
            label={t('categories.form.automatic')}
            color={null}
            checked={fields.color === null}
            onPick={() => setFields({ ...fields, color: null })}
          />
          {COLOR_CHOICES.map((color) => (
            <ColorChoice
              key={color}
              name={`${ids}-color`}
              label={t('categories.form.colorNamed', { color })}
              color={color}
              checked={fields.color === color}
              onPick={() => setFields({ ...fields, color })}
            />
          ))}
        </div>
      </fieldset>
      {error && (
        <p
          role="alert"
          className="rounded-[10px] border border-up/30 bg-up-soft px-3 py-2.5 text-[13px] text-up-ink"
        >
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button
          type="submit"
          className="h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold"
          disabled={blank || pending}
        >
          {pending ? t('categories.saving') : submitLabel}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold"
          onClick={onCancel}
        >
          {t('categories.cancel')}
        </Button>
      </div>
    </form>
  )
}

interface ColorChoiceProps {
  name: string
  label: string
  color: string | null
  checked: boolean
  onPick: () => void
}

function ColorChoice({ name, label, color, checked, onPick }: ColorChoiceProps) {
  return (
    <label
      title={label}
      className={cn(
        'flex size-11 cursor-pointer items-center justify-center rounded-xl border has-focus-visible:ring-3 has-focus-visible:ring-ring/50',
        checked ? 'border-foreground' : 'border-border',
      )}
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onPick}
        aria-label={label}
        className="sr-only"
      />
      {color === null ? (
        <span className="text-[11px] font-semibold text-muted-foreground">{t('categories.form.auto')}</span>
      ) : (
        <span className="size-6 rounded-full" style={{ backgroundColor: color }} />
      )}
    </label>
  )
}
