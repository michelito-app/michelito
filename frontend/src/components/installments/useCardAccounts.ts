import { useMemo } from 'react'
import { isCreditCard } from '@/lib/accounts'
import { useAccounts } from '@/lib/queries'

/** The keys of the credit card accounts (installments only come on cards). */
export function useCardAccounts(): ReadonlySet<string> {
  const accounts = useAccounts()
  return useMemo(
    () => new Set((accounts.data ?? []).filter(isCreditCard).map((account) => account.key)),
    [accounts.data],
  )
}
