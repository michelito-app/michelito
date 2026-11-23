import { useState } from 'react'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import type { InstallmentPlan } from '@/lib/api'
import { ChargePicker } from './ChargePicker'
import { InstallmentSheet } from './InstallmentSheet'

interface NewPlanSheetProps {
  onClose: () => void
  onCreated: (plan: InstallmentPlan) => void
}

/** "New plan": pick one of the plan's charges (there is no plan without one), then the same
 * short form as "It is an installment…". */
export function NewPlanSheet({ onClose, onCreated }: NewPlanSheetProps) {
  const [picked, setPicked] = useState<string | null>(null)
  if (picked !== null) {
    return <InstallmentSheet fingerprint={picked} onClose={onClose} onCreated={onCreated} />
  }
  return (
    <BottomSheet title={t('installments.picker.title')} onClose={onClose}>
      <p className="text-[13px] text-ink-2">{t('installments.picker.hint')}</p>
      <ChargePicker
        empty={t('installments.picker.empty')}
        onPick={(charge) => setPicked(charge.fingerprint)}
      />
    </BottomSheet>
  )
}
