import { Archive, ArrowLeftRight, HandCoins, Pencil, UsersRound, X } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Action, Failure, FIELD, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { memberBalanceText, personBalanceText, resplitText } from '@/lib/ledger'
import { useQuery } from '@tanstack/react-query'
import { shortDay } from '@/lib/months'
import type { Group, Member } from '@/lib/sharedApi'
import { ledger, sharedKeys, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { MenuItem, MenuList } from './parts'
import { LIST_CARD } from './styles'
import { PeoplePicker } from './PeoplePicker'
import type { ChosenPerson } from '@/lib/ledger'

type View = 'menu' | 'rename' | 'people' | 'writeOff' | 'leftover'

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
    leftover: t('shared.group.leftover'),
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
            <MenuItem icon={<ArrowLeftRight size={18} />} onClick={() => setView('leftover')}>
              {t('shared.group.leftover')}
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
      {view === 'leftover' && <Leftover group={group} />}
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
  const [removing, setRemoving] = useState<Member | null>(null)
  const write = useLedgerWrite()
  const others = group.members.filter((m) => !m.is_me)
  if (removing) {
    return <RemovePerson group={group} member={removing} onDone={() => setRemoving(null)} />
  }
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
              onClick={() => setRemoving(member)}
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

/** "Remove X": someone with nothing in the group just leaves; someone who only has shares can
 * leave those expenses too (each split again among the rest, same mode: one undo); someone who
 * paid or has payments stays, with the expenses and payments that keep them. */
function RemovePerson({ group, member, onDone }: { group: Group; member: Member; onDone: () => void }) {
  const write = useLedgerWrite()
  const [understood, setUnderstood] = useState(false)
  const usage = useQuery({
    queryKey: [...sharedKeys.group(group.id), 'usage', member.id],
    queryFn: () => ledger.memberUsage(group.id, member.id),
    staleTime: 0,
  })
  const remove = (resplit: boolean) =>
    write.mutate(() => ledger.removeMember(group.id, member.id, resplit), { onSuccess: onDone })
  const data = usage.data
  const erased = data?.shares.filter((item) => item.to_payer) ?? []
  const ready =
    data !== undefined && (data.free || (data.resplittable && (erased.length === 0 || understood)))
  return (
    <div className="flex flex-col gap-3" data-testid="remove-person">
      <p className="text-[15px] font-semibold">{t('shared.group.removeTitle', { name: member.name })}</p>
      {usage.isError && <LoadFailure what={t('shared.load')} error={usage.error} />}
      {usage.isPending && <p className="text-[13px] text-muted-foreground">{t('shared.group.removeChecking')}</p>}
      {data && !data.free && (
        <>
          {data.resplittable ? (
            <>
              <p className="text-[13px] text-ink-2">{t('shared.group.removeShares')}</p>
              <ul className={LIST_CARD} aria-label={t('shared.group.removeShares')}>
                {data.shares.map((item) => (
                  <li key={item.id} data-testid="remove-share" className="flex flex-col gap-0.5 px-3.5 py-2 text-sm">
                    <span className="flex min-h-7 items-center justify-between gap-3">
                      <span className="min-w-0 truncate font-medium">{item.description}</span>
                      <span className="shrink-0 text-[13px] text-muted-foreground">{shortDay(item.day)}</span>
                    </span>
                    <span className="text-[13px] break-words text-ink-2">
                      {t('shared.group.removeAfter', { split: resplitText(item.after, item.currency) })}
                    </span>
                    {item.to_payer && (
                      <span role="note" className="text-[13px] font-semibold text-up-ink">
                        {item.paid_by_me
                          ? t('shared.group.removeToYou')
                          : t('shared.group.removeToPayer', { name: item.paid_by_name })}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="text-[13px] text-muted-foreground">{t('shared.group.removeResplitHint')}</p>
              {erased.length > 0 && (
                <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={understood}
                    onChange={(event) => setUnderstood(event.target.checked)}
                    className="size-5 shrink-0 cursor-pointer accent-primary"
                  />
                  {t('shared.group.removeUnderstood', { name: member.name, count: erased.length })}
                </label>
              )}
            </>
          ) : (
            <p role="status" className="text-sm text-ink-2">
              {data.message}
            </p>
          )}
        </>
      )}
      <Failure error={write.error} />
      {data && (data.free || data.resplittable) && (
        <Button
          className="h-11 rounded-xl text-sm font-semibold"
          disabled={write.isPending || !ready}
          onClick={() => remove(!data.free)}
        >
          {data.free
            ? t('shared.group.removePerson', { name: member.name })
            : t('shared.group.removeResplit', { count: data.shares.length })}
        </Button>
      )}
      <Action wide disabled={write.isPending} onClick={onDone}>
        {t('shared.group.removeCancel')}
      </Action>
    </div>
  )
}

/** Per person: whether what is left below RD$ 50 or US$ 1 after a payment in the other currency
 * counts as settled (logged, undoable). */
function Leftover({ group }: { group: Group }) {
  const write = useLedgerWrite()
  const others = group.members.filter((m) => !m.is_me)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t('shared.group.leftoverHint')}</p>
      <ul className={LIST_CARD}>
        {others.map((member) => (
          <li key={member.id}>
            <label className="flex min-h-12 cursor-pointer items-center gap-3 px-3.5 text-sm">
              <input
                type="checkbox"
                checked={member.leftover_settled}
                disabled={write.isPending}
                onChange={(event) => {
                  // Read now: by the time the write runs React has put the controlled value back.
                  const settled = event.target.checked
                  write.mutate(() => ledger.setLeftover(group.id, member.id, settled))
                }}
                className="size-5 shrink-0 cursor-pointer accent-primary"
              />
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-medium">
                  {t('shared.group.leftoverPerson', { name: member.name })}
                </span>
                <span className="text-[13px] text-muted-foreground">{memberBalanceText(member)}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <Failure error={write.error} />
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
                onChange={(event) => {
                  const writtenOff = event.target.checked
                  write.mutate(() => ledger.writeOff(group.id, member.id, writtenOff))
                }}
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
