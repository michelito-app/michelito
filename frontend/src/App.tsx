import { Navigate, Route, Routes, useLocation } from 'react-router'
import { AppShell } from '@/components/AppShell'
import { LoadError } from '@/components/LoadError'
import { Gate } from '@/components/onboarding/Gate'
import { t } from '@/i18n'
import { legacyRedirect } from '@/legacy'
import { isHosted, useMode } from '@/lib/demo'
import { useOnboarding } from '@/lib/onboarding'
import { AccountsPage } from '@/pages/AccountsPage'
import { BudgetPage } from '@/pages/BudgetPage'
import { CategoriesPage } from '@/pages/CategoriesPage'
import { ConnectPage } from '@/pages/ConnectPage'
import { ForwardingGuidePage } from '@/pages/ForwardingGuidePage'
import { ImportPage } from '@/pages/ImportPage'
import { InvestmentsPage } from '@/pages/InvestmentsPage'
import { LinkPage } from '@/pages/LinkPage'
import { LogPage } from '@/pages/LogPage'
import { PendingPage } from '@/pages/PendingPage'
import { Placeholder } from '@/pages/Placeholder'
import { InstallmentsPage } from '@/pages/InstallmentsPage'
import { RecurringPage } from '@/pages/RecurringPage'
import { ReportsPage } from '@/pages/ReportsPage'
import { ReviewPage } from '@/pages/ReviewPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { SharedGroupPage } from '@/pages/SharedGroupPage'
import { TagPage } from './pages/TagPage'
import { TagsPage } from './pages/TagsPage'
import { SharedPage } from '@/pages/SharedPage'
import { SharedPersonPage } from '@/pages/SharedPersonPage'
import { SummaryPage } from '@/pages/SummaryPage'
import { TransactionsPage } from '@/pages/TransactionsPage'

export function App() {
  const hosted = isHosted(useMode())
  return hosted ? <HostedGate /> : <AppRoutes hosted={false} />
}

/** Hosted mode: until one statement squares, only the welcome and upload flow (the gate). */
function HostedGate() {
  const onboarding = useOnboarding()
  if (onboarding.isError) {
    return (
      <main className="mx-auto max-w-xl p-6">
        <LoadError
          what={t('onboarding.gate.label')}
          error={onboarding.error}
          onRetry={() => onboarding.refetch()}
        />
      </main>
    )
  }
  if (onboarding.isPending) {
    return (
      <p role="status" className="p-10 text-sm text-muted-foreground">
        {t('demo.gate.loading')}
      </p>
    )
  }
  if (!onboarding.data.open) return <Gate />
  return <AppRoutes hosted />
}

function AppRoutes({ hosted }: { hosted: boolean }) {
  return (
    <Routes>
      {hosted && <Route path="connect" element={<ConnectPage />} />}
      <Route element={<AppShell />}>
        <Route index element={<SummaryPage />} />
        <Route path="budget" element={<BudgetPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="transactions/:fingerprint" element={<LinkPage />} />
        <Route path="pending" element={<PendingPage />} />
        <Route path="shared" element={<SharedPage />} />
        <Route path="shared/people/:id" element={<SharedPersonPage />} />
        <Route path="shared/:id" element={<SharedGroupPage />} />
        <Route path="tags" element={<TagsPage />} />
        <Route path="tags/:id" element={<TagPage />} />
        <Route path="investments" element={<InvestmentsPage />} />
        <Route path="recurring" element={<RecurringPage />} />
        <Route path="installments" element={<InstallmentsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="log" element={<LogPage />} />
        <Route path="import" element={<ImportPage />} />
        {hosted && <Route path="settings" element={<SettingsPage />} />}
        {hosted && <Route path="settings/forwarding-guide" element={<ForwardingGuidePage />} />}
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
