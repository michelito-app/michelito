import { Combine, Pencil, Tags, X } from 'lucide-react'
import { useId, useState } from 'react'
import { useNavigate } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { Failure, FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Person } from '@/lib/sharedApi'
import { ledger, useContacts, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { MenuItem, MenuList } from './parts'
import { LIST_CARD, ROW_BUTTON } from './styles'

type View = 'menu' | 'rename' | 'merge' | 'aliases'

/** A person's "⋯": rename, merge with another contact and the names the bank prints. */
export function PersonMenu({ person, onClose }: { person: Person; onClose: () => void }) {
  const [view, setView] = useState<View>('menu')
  const titles: Record<View, string> = {
    menu: person.name,
    rename: t('shared.person.rename'),
    merge: t('shared.person.merge'),
    aliases: t('shared.person.aliases'),
  }
  return (
    <BottomSheet title={titles[view]} onClose={onClose}>
      {view === 'menu' && (
        <MenuList>
          <MenuItem icon={<Pencil size={18} />} onClick={() => setView('rename')}>
            {t('shared.person.rename')}
          </MenuItem>
          <MenuItem icon={<Combine size={18} />} onClick={() => setView('merge')}>
            {t('shared.person.merge')}
          </MenuItem>
          <MenuItem icon={<Tags size={18} />} onClick={() => setView('aliases')}>
            {t('shared.person.aliases')}
          </MenuItem>
        </MenuList>
      )}
      {view === 'rename' && <Rename person={person} onDone={onClose} />}
      {view === 'merge' && <Merge person={person} />}
      {view === 'aliases' && <Aliases person={person} />}
    </BottomSheet>
  )
}

function Rename({ person, onDone }: { person: Person; onDone: () => void }) {
  const ids = useId()
  const [name, setName] = useState(person.name)
  const write = useLedgerWrite<unknown>()
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (name.trim()) write.mutate(() => ledger.renameContact(person.id, name.trim()), { onSuccess: onDone })
      }}
    >
      <label htmlFor={`${ids}-name`} className="text-[13px] font-semibold text-ink-2">
        {t('shared.person.nameLabel')}
      </label>
      <input
        id={`${ids}-name`}
        value={name}
        maxLength={80}
        onChange={(event) => setName(event.target.value)}
        className={FIELD}
      />
      <Failure error={write.error as Error | null} />
      <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={!name.trim() || write.isPending}>
        {t('shared.save')}
      </Button>
    </form>
  )
}

function Merge({ person }: { person: Person }) {
  const contacts = useContacts()
  const write = useLedgerWrite<unknown>()
  const navigate = useNavigate()
  const others = (contacts.data?.contacts ?? []).filter((c) => !c.is_me && c.id !== person.id)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t('shared.person.mergeHint', { name: person.name })}</p>
      <ul className={LIST_CARD}>
        {others.map((other) => (
          <li key={other.id}>
            <button
              type="button"
              disabled={write.isPending}
              onClick={() =>
                write.mutate(() => ledger.merge(person.id, other.id), {
                  onSuccess: () => navigate(`/shared/people/${other.id}`, { replace: true }),
                })
              }
              className={ROW_BUTTON}
            >
              <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                {t('shared.person.mergeInto', { name: other.name })}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <Failure error={write.error as Error | null} />
    </div>
  )
}

function Aliases({ person }: { person: Person }) {
  const ids = useId()
  const [alias, setAlias] = useState('')
  const write = useLedgerWrite<unknown>()
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t('shared.person.aliasesHint')}</p>
      {person.aliases.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('shared.person.noAliases')}</p>
      ) : (
        <ul className={LIST_CARD}>
          {person.aliases.map((name) => (
            <li key={name} className="flex min-h-12 items-center gap-3 pl-3.5">
              <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
              <button
                type="button"
                aria-label={t('shared.person.removeAlias', { alias: name })}
                disabled={write.isPending}
                onClick={() => write.mutate(() => ledger.removeAlias(person.id, name))}
                className={cn('flex size-11 shrink-0 items-center justify-center text-muted-foreground hover:bg-muted', FOCUS)}
              >
                <X size={18} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (alias.trim()) {
            write.mutate(() => ledger.addAlias(person.id, alias.trim()), { onSuccess: () => setAlias('') })
          }
        }}
      >
        <label htmlFor={`${ids}-alias`} className="sr-only">
          {t('shared.person.aliasLabel')}
        </label>
        <input
          id={`${ids}-alias`}
          value={alias}
          maxLength={80}
          placeholder={t('shared.person.aliasLabel')}
          onChange={(event) => setAlias(event.target.value)}
          className={cn(FIELD, 'flex-1')}
        />
        <Button type="submit" className="h-11 rounded-xl px-4 text-sm font-semibold" disabled={!alias.trim() || write.isPending}>
          {t('shared.person.addAlias')}
        </Button>
      </form>
      <Failure error={write.error as Error | null} />
    </div>
  )
}
