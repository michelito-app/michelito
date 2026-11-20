import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import { CODE_LENGTH, cleanCode } from '@/lib/hosted'

interface CodeFieldProps {
  id: string
  value: string
  onChange: (code: string) => void
  invalid?: boolean
  describedBy?: string
}

/** The 6-digit code: numeric keyboard on phones, and the system can offer the code from the
 * email or SMS (`one-time-code`). Pasting "123 456" keeps the digits. */
export function CodeField({ id, value, onChange, invalid, describedBy }: CodeFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {t('auth.signIn.code')}
      </label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(cleanCode(event.target.value))}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={CODE_LENGTH + 2}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        className="h-12 text-center font-mono text-2xl tracking-[0.4em] md:text-2xl"
      />
    </div>
  )
}
