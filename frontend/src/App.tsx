import { Navigate, Route, Routes, useLocation } from 'react-router'
import { AppShell } from '@/components/AppShell'
import { t } from '@/i18n'
import { legacyRedirect } from '@/legacy'
import { AccountsPage } from '@/pages/AccountsPage'
import { BudgetPage } from '@/pages/BudgetPage'
import { CategoriesPage } from '@/pages/CategoriesPage'
import { ImportPage } from '@/pages/ImportPage'
import { InvestmentsPage } from '@/pages/InvestmentsPage'
import { LinkPage } from '@/pages/LinkPage'
import { LogPage } from '@/pages/LogPage'
import { PendingPage } from '@/pages/PendingPage'
import { Placeholder } from '@/pages/Placeholder'
import { RecurringPage } from '@/pages/RecurringPage'
import { ReportsPage } from '@/pages/ReportsPage'
import { SharedPage } from '@/pages/SharedPage'
import { SummaryPage } from '@/pages/SummaryPage'
import { TransactionsPage } from '@/pages/TransactionsPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<SummaryPage />} />
        <Route path="budget" element={<BudgetPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="transactions/:fingerprint" element={<LinkPage />} />
        <Route path="pending" element={<PendingPage />} />
        <Route path="shared" element={<SharedPage />} />
        <Route path="investments" element={<InvestmentsPage />} />
        <Route path="recurring" element={<RecurringPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="log" element={<LogPage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

/** An unknown path: a link saved before the English rename goes to its new path; anything else
 * is "not found". */
function NotFound() {
  const location = useLocation()
  const target = legacyRedirect(location.pathname, location.search)
  if (target !== null) return <Navigate replace to={`${target}${location.hash}`} />
  return <Placeholder title={t('shell.notFound')} />
}
