// The month viewed in Summary or Transactions travels through the menu, only in the URL.
import { useEffect } from 'react'
import { useOutletContext } from 'react-router'

/** Menu screens that show a month. */
const MONTH_ROUTES: readonly string[] = ['/', '/transactions']

/** What `AppShell` gives the screens to report which month is viewed. */
export interface NavMonthContext {
  setNavMonth: (month: string | null) => void
}

/** Menu link: Summary and Transactions carry `?month=` when a month other than the default one
 * is viewed (`month` not null). */
export function navHref(to: string, month: string | null): string {
  if (month === null || !MONTH_ROUTES.includes(to)) return to
  return `${to}?${new URLSearchParams({ month })}`
}

/** Tells the menu which month is viewed (null if it is the default one); on leaving, clears it. */
export function usePublishNavMonth(month: string | null): void {
  const context = useOutletContext<NavMonthContext | undefined>()
  const setNavMonth = context?.setNavMonth
  useEffect(() => {
    if (!setNavMonth) return
    setNavMonth(month)
    return () => setNavMonth(null)
  }, [setNavMonth, month])
}
