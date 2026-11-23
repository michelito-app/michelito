import { useState } from 'react'
import { LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { InstallmentPlan } from '@/lib/api'
import { preferredPerson } from '@/lib/installmentForm'
import { useInstallmentDraft, useInstallmentPeople } from '@/lib/installmentQueries'
import { useGroup } from '@/lib/sharedQueries'
import { CreateForm } from './CreateForm'

interface InstallmentSheetProps {
  fingerprint: string
  /** The group the charge is already shared in: its other member is the owner at first. */
  sharedGroupId?: number | null
  onClose: () => void
  onCreated: (plan: InstallmentPlan) => void
}

/** "It is an installment…": how many installments and for whom, with the earlier identical
 * charges to confirm (from a transaction, or from "New plan" after picking a charge). */
export function InstallmentSheet({
  fingerprint,
  sharedGroupId = null,
  onClose,
  onCreated,
}: InstallmentSheetProps) {
  return (
    <BottomSheet title={t('installments.form.title')} onClose={onClose}>
      <SheetBody fingerprint={fingerprint} sharedGroupId={sharedGroupId} onCreated={onCreated} />
    </BottomSheet>
  )
}

function SheetBody({
  fingerprint,
  sharedGroupId,
  onCreated,
}: Omit<InstallmentSheetProps, 'onClose'>) {
  // As it was when the sheet opened: saving shares the charge (a person's plan), and the form
  // must not wait for that new group and lose its state (and the save's callback) meanwhile.
  const [groupId] = useState(sharedGroupId ?? null)
  const draft = useInstallmentDraft(fingerprint)
  const people = useInstallmentPeople()
  const group = useGroup(groupId)
  // Once shown, the form stays: a refetch after saving (or its failure) must not unmount it.
  if (draft.data === undefined && draft.isError) {
    return <LoadFailure what={t('installments.form.loadWhat')} error={draft.error} />
  }
  if (people.data === undefined && people.isError) {
    return <LoadFailure what={t('installments.form.peopleWhat')} error={people.error} />
  }
  // The shared group only suggests the person: while it loads the form waits, if it fails it
  // starts as the user's own.
  if (draft.data === undefined || people.data === undefined || (groupId !== null && group.isPending)) {
    return (
      <div aria-busy="true" className="flex flex-col gap-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-11 w-full rounded-xl" />
        <Skeleton className="h-11 w-full rounded-xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
    )
  }
  return (
    <CreateForm
      draft={draft.data}
      people={people.data}
      preferred={preferredPerson(people.data, group.data?.members)}
      onCreated={onCreated}
    />
  )
}
