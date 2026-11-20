import { useState } from 'react'
import { Action, Failure, FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Contact, Person } from '@/lib/sharedApi'
import { ledger, useContacts, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { LIST_CARD } from './styles'

/** "Review your people", once after the migration: rename or merge the people made from the
 * old groups; "Done" does not offer it again. */
export function ReviewPeopleSheet({ people, onClose }: { people: Person[]; onClose: () => void }) {
  const contacts = useContacts()
  const done = useLedgerWrite<void>()
  const list = (contacts.data?.contacts ?? []).filter((c) => !c.is_me)
  const shown = list.length > 0 ? list : people.map((p) => ({ ...p, is_me: false }))
  return (
    <BottomSheet title={t('shared.review.title')} onClose={onClose}>
      <p className="text-[13px] text-muted-foreground">{t('shared.review.text')}</p>
      <ul className={LIST_CARD}>
        {shown.map((contact) => (
          <ReviewRow key={contact.id} contact={contact} others={shown.filter((c) => c.id !== contact.id)} />
        ))}
      </ul>
      <Failure error={done.error} />
      <Button
        className="h-11 rounded-xl text-sm font-semibold"
        disabled={done.isPending}
        onClick={() => done.mutate(() => ledger.reviewPeopleDone(), { onSuccess: onClose })}
      >
        {t('shared.review.done')}
      </Button>
    </BottomSheet>
  )
}

function ReviewRow({ contact, others }: { contact: Contact; others: Contact[] }) {
  const [name, setName] = useState(contact.name)
  const [into, setInto] = useState('')
  const write = useLedgerWrite<unknown>()
  const changed = name.trim() !== '' && name.trim() !== contact.name
  return (
    <li className="flex flex-col gap-2 px-3.5 py-3">
      <div className="flex gap-2">
        <input
          aria-label={t('shared.person.nameLabel')}
          value={name}
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
          className={cn(FIELD, 'flex-1')}
        />
        {changed && (
          <Action
            disabled={write.isPending}
            onClick={() => write.mutate(() => ledger.renameContact(contact.id, name.trim()))}
          >
            {t('shared.save')}
          </Action>
        )}
      </div>
      {others.length > 0 && (
        <div className="flex gap-2">
          <select
            aria-label={t('shared.review.mergeLabel', { name: contact.name })}
            value={into}
            onChange={(event) => setInto(event.target.value)}
            className={cn(FIELD, 'flex-1 cursor-pointer')}
          >
            <option value="">{t('shared.review.noMerge')}</option>
            {others.map((other) => (
              <option key={other.id} value={String(other.id)}>
                {other.name}
              </option>
            ))}
          </select>
          {into !== '' && (
            <Action
              disabled={write.isPending}
              onClick={() => write.mutate(() => ledger.merge(contact.id, Number(into)))}
            >
              {t('shared.person.merge')}
            </Action>
          )}
        </div>
      )}
      <Failure error={write.error as Error | null} />
    </li>
  )
}
