import { useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { choosable } from '@/lib/categories'
import { formatDop } from '@/lib/money'
import {
  type Merchant,
  merchantsKey,
  onboardingKey,
  reviewMerchant,
  setFlag,
  useMerchants,
} from '@/lib/onboarding'
import { useCategories, useEditTransaction } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** "Adjust your main merchants": on the first Summary only, the merchants with the most
 * spending, each with its category: "Correct" marks it reviewed, "Change" makes a merchant rule
 * (the usual correction), "Later" hides the card. No tour. */
export function FirstReview() {
  const merchants = useMerchants()
  const queryClient = useQueryClient()
  const [changing, setChanging] = useState<Merchant | null>(null)
  const [error, setError] = useState<string | null>(null)
  const id = useId()

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: onboardingKey })
  }

  async function correct(merchant: Merchant) {
    setError(null)
    try {
      queryClient.setQueryData(merchantsKey, await reviewMerchant(merchant.merchant))
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  async function later() {
    try {
      await setFlag('first_review_closed')
      await refresh()
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  if (!merchants.data?.length) return null
  return (
    <section aria-labelledby={id} className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={id} className="text-[17px] font-[650] tracking-tight">
            {t('onboarding.review.title')}
          </h2>
          <p className="text-sm text-ink-2">{t('onboarding.review.lead')}</p>
        </div>
        <Button variant="ghost" className="h-11 px-3" onClick={() => void later()}>
          {t('onboarding.review.later')}
        </Button>
      </div>
      <ul className="flex flex-col">
        {merchants.data.map((merchant) => (
          <li
            key={merchant.merchant}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border py-2.5 last:border-b-0"
          >
            <div className="flex min-w-0 flex-[1_1_180px] flex-col">
              <span className="truncate text-sm font-semibold">{merchant.merchant}</span>
              <span className="text-[13px] text-muted-foreground">
                {merchant.category} · {formatDop(Math.round(Number(merchant.total) * 100))} ·{' '}
                {t('onboarding.review.purchases', { count: merchant.count })}
              </span>
            </div>
            {merchant.status === 'pending' ? (
              <div className="flex gap-1.5">
                <Button variant="secondary" className="h-11 px-3" onClick={() => void correct(merchant)}>
                  {t('onboarding.review.correct')}
                </Button>
                <Button variant="outline" className="h-11 px-3" onClick={() => setChanging(merchant)}>
                  {t('onboarding.review.change')}
                </Button>
              </div>
            ) : (
              <span className="text-[13px] font-semibold text-down">
                {merchant.status === 'reviewed'
                  ? t('onboarding.review.reviewed')
                  : t('onboarding.review.rule')}
              </span>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {changing && (
        <ChangeSheet
          merchant={changing}
          onClose={() => setChanging(null)}
          onSaved={() => {
            setChanging(null)
            void queryClient.invalidateQueries({ queryKey: merchantsKey })
          }}
        />
      )}
    </section>
  )
}

interface ChangeSheetProps {
  merchant: Merchant
  onClose: () => void
  onSaved: () => void
}

/** "Change": a category for the whole merchant (a merchant rule, logged and undoable). */
function ChangeSheet({ merchant, onClose, onSaved }: ChangeSheetProps) {
  const categories = useCategories()
  const edit = useEditTransaction()
  const options = choosable(categories.data ?? []).filter((c) => !c.hidden)
  const [chosen, setChosen] = useState<number | null>(merchant.category_id)
  const id = useId()

  function save() {
    if (chosen === null) return
    edit.mutate(
      { fingerprint: merchant.fingerprint, body: { category_id: chosen, scope: 'merchant' } },
      { onSuccess: onSaved },
    )
  }

  return (
    <BottomSheet title={t('onboarding.review.sheet', { merchant: merchant.merchant })} onClose={onClose}>
      <label htmlFor={id} className="flex flex-col gap-1 text-sm font-medium">
        {t('onboarding.review.category')}
        <select
          id={id}
          value={chosen ?? ''}
          onChange={(event) => setChosen(Number(event.target.value))}
          className={cn('h-11 rounded-lg border border-input bg-card px-2 text-sm', FOCUS)}
        >
          {options.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
      </label>
      {edit.isError && (
        <p role="alert" className="text-sm text-destructive">
          {edit.error.message}
        </p>
      )}
      <Button className="h-11" disabled={edit.isPending || chosen === null} onClick={save}>
        {t('onboarding.review.save')}
      </Button>
    </BottomSheet>
  )
}
