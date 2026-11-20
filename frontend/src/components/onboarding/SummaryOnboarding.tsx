import { FirstReview } from '@/components/onboarding/FirstReview'
import { SetupChecklist } from '@/components/onboarding/SetupChecklist'
import { isHosted, useMode } from '@/lib/demo'
import { useOnboarding } from '@/lib/onboarding'

/** Hosted mode, on top of the Summary: the first review of the top merchants (only until it is
 * done or put off) and the setup checklist (until completed or hidden). Nothing elsewhere. */
export function SummaryOnboarding() {
  const hosted = isHosted(useMode())
  const onboarding = useOnboarding(hosted)
  if (!hosted || !onboarding.data) return null
  const { first_review: firstReview, checklist } = onboarding.data
  if (!firstReview && !checklist.visible) return null
  return (
    <div className="flex max-w-[960px] flex-col gap-4">
      {firstReview && <FirstReview />}
      {checklist.visible && <SetupChecklist checklist={checklist} />}
    </div>
  )
}
