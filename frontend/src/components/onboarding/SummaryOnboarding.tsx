import { StatementsCard } from '@/components/forwarding/StatementsCard'
import { FirstReview } from '@/components/onboarding/FirstReview'
import { SetupChecklist } from '@/components/onboarding/SetupChecklist'
import { isHosted, useMode } from '@/lib/demo'
import { useForwarding } from '@/lib/forwarding'
import { useOnboarding } from '@/lib/onboarding'

/** Hosted mode, on top of the Summary: the first review of the top merchants (only until it is
 * done or put off), the setup checklist (until completed or hidden) and, once email forwarding
 * is set up, the statements card. Nothing elsewhere. */
export function SummaryOnboarding() {
  const hosted = isHosted(useMode())
  const onboarding = useOnboarding(hosted)
  const forwarding = useForwarding(hosted)
  if (!hosted || !onboarding.data) return null
  const { first_review: firstReview, checklist } = onboarding.data
  const statements = forwarding.data?.created ? forwarding.data : null
  if (!firstReview && !checklist.visible && !statements) return null
  return (
    <div className="flex max-w-[960px] flex-col gap-4">
      {firstReview && <FirstReview />}
      {checklist.visible && <SetupChecklist checklist={checklist} />}
      {statements && <StatementsCard data={statements} />}
    </div>
  )
}
