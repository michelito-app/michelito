import { Route, Routes } from 'react-router'
import { AppShell } from '@/components/AppShell'
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
        <Route path="presupuesto" element={<BudgetPage />} />
        <Route path="transacciones" element={<TransactionsPage />} />
        <Route path="transacciones/:fingerprint" element={<LinkPage />} />
        <Route path="pendientes" element={<PendingPage />} />
        <Route path="compartidos" element={<SharedPage />} />
        <Route path="inversiones" element={<InvestmentsPage />} />
        <Route path="recurrentes" element={<RecurringPage />} />
        <Route path="reportes" element={<ReportsPage />} />
        <Route path="cuentas" element={<AccountsPage />} />
        <Route path="categorias" element={<CategoriesPage />} />
        <Route path="bitacora" element={<LogPage />} />
        <Route path="importar" element={<ImportPage />} />
        <Route path="*" element={<Placeholder title="Página no encontrada" />} />
      </Route>
    </Routes>
  )
}
