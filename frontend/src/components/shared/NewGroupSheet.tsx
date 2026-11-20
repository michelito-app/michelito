import { useId, useState } from 'react'
import { Failure, FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Group } from '@/lib/sharedApi'
import { ledger, useLedgerWrite } from '@/lib/sharedQueries'
import { PeoplePicker } from './PeoplePicker'
import type { ChosenPerson } from '@/lib/ledger'

interface NewGroupSheetProps {
  onClose: () => void
  /** The group was created (the caller lands on its page, or picks it in a draft). */
  onCreated: (group: Group) => void
}

/** "New group": a name (the only required field) and people as chips; "You" is always in. */
export function NewGroupSheet({ onClose, onCreated }: NewGroupSheetProps) {
  const ids = useId()
  const [name, setName] = useState('')
  const [people, setPeople] = useState<ChosenPerson[]>([])
  const write = useLedgerWrite()
  const clean = name.trim()

  function create() {
    if (!clean) return
    write.mutate(
      () =>
        ledger.createGroup(
          clean,
          people.map((p) => p.person),
        ),
      { onSuccess: (group) => onCreated(group) },
    )
  }

  return (
    <BottomSheet title={t('shared.newGroup.title')} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          create()
        }}
      >
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2" htmlFor={`${ids}-name`}>
          {t('shared.newGroup.name')}
        </label>
        <input
          id={`${ids}-name`}
          value={name}
          maxLength={80}
          required
          placeholder={t('shared.newGroup.namePlaceholder')}
          onChange={(event) => setName(event.target.value)}
          className={FIELD}
        />
        <fieldset className="flex flex-col gap-2">
          <legend className="pb-2 text-[13px] font-semibold text-ink-2">
            {t('shared.newGroup.people')}
          </legend>
          <PeoplePicker chosen={people} onChange={setPeople} />
        </fieldset>
        <Failure error={write.error} />
        <Button
          type="submit"
          className="h-11 rounded-xl text-sm font-semibold"
          disabled={!clean || write.isPending}
        >
          {write.isPending ? t('shared.saving') : t('shared.newGroup.create')}
        </Button>
      </form>
    </BottomSheet>
  )
}
