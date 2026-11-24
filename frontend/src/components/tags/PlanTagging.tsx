import { t } from '@/i18n'
import { useTagTarget } from '@/lib/tagQueries'
import { TagPicker } from './TagPicker'

/** On an installment plan: "Add to a tag" (the whole plan; its charges come along and
 * what is left shows as still to pay). */
export function PlanTagging({ planId }: { planId: number }) {
  const target = useTagTarget()
  return (
    <div className="px-5 pb-4 sm:px-6">
      <TagPicker
        label={t('tags.target.add')}
        busy={target.isPending}
        onPick={(id) => target.mutate({ id, kind: 'installments', targetId: planId, on: true })}
      />
    </div>
  )
}
