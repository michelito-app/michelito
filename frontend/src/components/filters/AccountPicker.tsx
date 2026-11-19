import { Popover } from '@base-ui/react/popover'
import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import {
  type AccountRef,
  buttonLabel,
  hasShortcut,
  isSelected,
  isShortcut,
  LAST_ACCOUNT_HINT,
  type Selection,
  SHORTCUTS,
  shortcutSelection,
  toggle,
} from '@/lib/accountFilter'
import { cn } from '@/lib/utils'
import { FOCUS } from '@/components/summary/styles'

interface AccountPickerProps {
  selection: Selection
  accounts: readonly AccountRef[]
  onChange: (next: Selection) => void
  className?: string
}

/** Botón "Cuentas: Todas" que abre la lista de cuentas con atajos (todas, solo tarjetas, solo
 * cuentas bancarias). Siempre queda al menos una cuenta elegida. */
export function AccountPicker({ selection, accounts, onChange, className }: AccountPickerProps) {
  const label = buttonLabel(selection, accounts)
  const hintId = useId()
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label={`Elegir cuentas (${label})`}
        className={cn(
          'flex h-11 max-w-full min-w-0 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-foreground transition-colors hover:bg-muted data-[popup-open]:bg-muted',
          FOCUS,
          className,
        )}
      >
        <span className="min-w-0 truncate">{label}</span>
        <ChevronDown size={16} aria-hidden="true" className="shrink-0 text-muted-foreground" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner
          side="bottom"
          sideOffset={6}
          align="start"
          collisionPadding={16}
          className="z-50"
        >
          <Popover.Popup className="flex max-h-(--available-height) w-[min(340px,calc(100vw-32px))] flex-col gap-3 overflow-y-auto rounded-xl border border-border bg-card p-3 text-foreground shadow-[0_8px_32px_rgba(27,29,33,0.16)] outline-none">
            <Popover.Title className="px-1 text-[13px] font-semibold text-muted-foreground">
              Cuentas
            </Popover.Title>
            <div role="group" aria-label="Atajos" className="flex flex-wrap gap-1.5">
              {SHORTCUTS.filter((s) => hasShortcut(s.shortcut, accounts)).map((s) => {
                const active = isShortcut(s.shortcut, selection, accounts)
                return (
                  <button
                    key={s.shortcut}
                    type="button"
                    aria-pressed={active}
                    onClick={() => onChange(shortcutSelection(s.shortcut, accounts))}
                    className={cn(
                      'min-h-11 rounded-lg border px-3 text-[13px] font-semibold transition-colors',
                      active
                        ? 'border-primary bg-secondary text-secondary-foreground'
                        : 'border-border bg-card text-ink-2 hover:bg-muted',
                      FOCUS,
                    )}
                  >
                    {s.label}
                  </button>
                )
              })}
            </div>
            <ul className="flex flex-col">
              {accounts.map((account) => {
                const checked = isSelected(account.key, selection)
                const last = checked && selection !== null && selection.length === 1
                return (
                  <li key={account.key}>
                    <label
                      title={last ? LAST_ACCOUNT_HINT : undefined}
                      className={cn(
                        'flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-muted/60',
                        last && 'cursor-default',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={last}
                        aria-describedby={last ? hintId : undefined}
                        onChange={() => onChange(toggle(account.key, selection, accounts))}
                        className="size-4 shrink-0 accent-primary"
                      />
                      <span className="min-w-0 [overflow-wrap:anywhere]">{account.label}</span>
                    </label>
                  </li>
                )
              })}
            </ul>
            {selection !== null && selection.length === 1 && (
              <p id={hintId} className="px-1 text-[13px] text-muted-foreground">
                {LAST_ACCOUNT_HINT}
              </p>
            )}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  )
}
