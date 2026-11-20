import { Archive, HandCoins, Pencil, UsersRound, X } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Action, Failure, FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { personBalanceText } from '@/lib/ledger'
import type { Group } from '@/lib/sharedApi'
import { ledger, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { MenuItem, MenuList } from './parts'
import { LIST_CARD } from './styles'
import { PeoplePicker } from './PeoplePicker'
import type { ChosenPerson } from '@/lib/ledger'

type View = 'menu' | 'rename' | 'people' | 'writeOff'

/** The group's "⋯": rename, people, "They won't pay me" (per person, or everyone left) and
 * archive. */
export function GroupMenu({ group, onClose }: { group: Group; onClose: () => void }) {
  const [view, setView] = useState<View>('menu')
  const write = useLedgerWrite()
  const titles: Record<View, string> = {
    menu: group.name,
    rename: t('shared.group.rename'),
    people: t('shared.group.people'),
    writeOff: t('shared.group.writeOff'),
  }
  return (
    <BottomSheet title={titles[view]} onClose={onClose}>
      {view === 'menu' && (
        <>
          <MenuList>
            <MenuItem icon={<Pencil size={18} />} onClick={() => setView('rename')}>
              {t('shared.group.rename')}
            </MenuItem>
            <MenuItem icon={<UsersRound size={18} />} onClick={() => setView('people')}>
              {t('shared.group.people')}
            </MenuItem>
            <MenuItem icon={<HandCoins size={18} />} onClick={() => setView('writeOff')}>
              {t('shared.group.writeOff')}
            </MenuItem>
            <MenuItem
              icon={<Archive size={18} />}
              onClick={() =>
                write.mutate(() => ledger.patchGroup(group.id, { archived: !group.archived }), {
                  onSuccess: onClose,
                })
              }
            >
              {group.archived ? t('shared.group.unarchive') : t('shared.group.archive')}
            </MenuItem>
          </MenuList>
          <Failure error={write.error} />
        </>
      )}
      {view === 'rename' && <Rename group={group} onDone={onClose} />}
      {view === 'people' && <People group={group} />}
      {view === 'writeOff' && <WriteOff group={group} />}
    </BottomSheet>
  )
}

function Rename({ group, onDone }: { group: Group; onDone: () => void }) {
  const ids = useId()
  const [name, setName] = useState(group.name)
  const write = useLedgerWrite()
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (name.trim()) {
          write.mutate(() => ledger.patchGroup(group.id, { name: name.trim() }), { onSuccess: onDone })
        }
      }}
    >
      <label htmlFor={`${ids}-name`} className="text-[13px] font-semibold text-ink-2">
        {t('shared.group.nameLabel')}
      </label>
      <input
        id={`${ids}-name`}
        value={name}
        maxLength={80}
        onChange={(event) => setName(event.target.value)}
        className={FIELD}
      />
      <Failure error={write.error} />
      <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={!name.trim() || write.isPending}>
        {t('shared.save')}
      </Button>
    </form>
  )
}

function People({ group }: { group: Group }) {
  const [adding, setAdding] = useState<ChosenPerson[]>([])
  const write = useLedgerWrite()
  const others = group.members.filter((m) => !m.is_me)
  return (
    <div className="flex flex-col gap-4">
      <ul className={LIST_CARD} aria-label={t('shared.group.people')}>
        {others.map((member) => (
          <li key={member.id} className="flex min-h-12 items-center gap-3 pl-3.5">
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{member.name}</span>
            <button
              type="button"
              aria-label={t('shared.group.removePerson', { name: member.name })}
              disabled={write.isPending}
              onClick={() => write.mutate(() => ledger.removeMember(group.id, member.id))}
              className={cn(
                'flex size-11 shrink-0 items-center justify-center text-muted-foreground hover:bg-muted',
                FOCUS,
              )}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
      <PeoplePicker
        chosen={adding}
        onChange={setAdding}
        withMe={false}
        exclude={group.members.map((m) => m.id)}
      />
      <Failure error={write.error} />
      <Button
        className="h-11 rounded-xl text-sm font-semibold"
        disabled={adding.length === 0 || write.isPending}
        onClick={() =>
          write.mutate(
            async () => {
              let fresh = group
              for (const person of adding) fresh = await ledger.addMember(group.id, person.person)
              return fresh
            },
            { onSuccess: () => setAdding([]) },
          )
        }
      >
        {t('shared.group.addPerson')}
      </Button>
    </div>
  )
}

function WriteOff({ group }: { group: Group }) {
  const write = useLedgerWrite()
  const others = group.members.filter((m) => !m.is_me)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t('shared.group.writeOffHint')}</p>
      <ul className={LIST_CARD}>
        {others.map((member) => (
          <li key={member.id}>
            <label className="flex min-h-12 cursor-pointer items-center gap-3 px-3.5 text-sm">
              <input
                type="checkbox"
                checked={member.written_off}
                disabled={write.isPending}
                onChange={(event) =>
                  write.mutate(() => ledger.writeOff(group.id, member.id, event.target.checked))
                }
                className="size-5 shrink-0 cursor-pointer accent-primary"
              />
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-medium">
                  {t('shared.group.writeOffPerson', { name: member.name })}
                </span>
                <span className="text-[13px] text-muted-foreground">{personBalanceText(member.balance)}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <Action disabled={write.isPending} onClick={() => write.mutate(() => ledger.writeOff(group.id, null, true))}>
        {t('shared.group.writeOffEveryone')}
      </Action>
      <Failure error={write.error} />
    </div>
  )
}
