import { FIELD } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { InstallmentPerson } from '@/lib/api'
import { type OwnerForm, ownerValue, parseOwnerValue } from '@/lib/installmentForm'
import { NAME_MAX } from '@/lib/installments'
import { cn } from '@/lib/utils'
import { Field } from './formParts'

interface OwnerFieldProps {
  people: readonly InstallmentPerson[]
  value: OwnerForm
  onChange: (patch: Partial<OwnerForm>) => void
}

/** The owner ("For"): mine, one of the people of the user's groups, or "+ New person" (which asks for
 * the name). The group is the server's business. */
export function OwnerField({ people, value, onChange }: OwnerFieldProps) {
  const hint =
    value.owner === 'me' ? t('installments.form.ownerHint.me') : t('installments.form.ownerHint.person')
  return (
    <div className="flex flex-col gap-3">
      <Field label={t('installments.form.owner')} hint={hint}>
        <select
          value={ownerValue(value.owner)}
          onChange={(event) => onChange({ owner: parseOwnerValue(event.target.value) })}
          className={cn(FIELD, 'cursor-pointer font-medium')}
        >
          <option value={ownerValue('me')}>{t('installments.form.mine')}</option>
          {people.map((person) => (
            <option key={person.id} value={ownerValue(person.id)}>
              {person.name}
            </option>
          ))}
          <option value={ownerValue('new')}>{t('installments.form.newPerson')}</option>
        </select>
      </Field>
      {value.owner === 'new' && (
        <Field label={t('installments.form.newName')}>
          <input
            value={value.newName}
            maxLength={NAME_MAX}
            autoComplete="off"
            onChange={(event) => onChange({ newName: event.target.value })}
            className={FIELD}
          />
        </Field>
      )}
    </div>
  )
}
