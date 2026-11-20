import {
  ChartColumn,
  HandCoins,
  History,
  LayoutDashboard,
  List,
  PiggyBank,
  Repeat,
  Sprout,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { EmptyState } from '@/components/ui/empty-state'
import { t } from '@/i18n'
import { useMode } from '@/lib/demo'
import { previewUrl } from '@/lib/onboarding'

export type EmptyView =
  | 'summary'
  | 'budget'
  | 'transactions'
  | 'pending'
  | 'investments'
  | 'recurring'
  | 'reports'
  | 'log'

interface ViewEmpty {
  icon: ReactNode
  title: string
  text: string
  action: string
  to: string
  path: string
}

const ICON = { size: 26, strokeWidth: 1.8, 'aria-hidden': true } as const

const VIEWS: Record<EmptyView, ViewEmpty> = {
  summary: {
    icon: <LayoutDashboard {...ICON} />,
    title: t('onboarding.empty.summary.title'),
    text: t('onboarding.empty.summary.text'),
    action: t('onboarding.empty.upload'),
    to: '/import',
    path: '/',
  },
  budget: {
    icon: <PiggyBank {...ICON} />,
    title: t('onboarding.empty.budget.title'),
    text: t('onboarding.empty.budget.text'),
    action: t('onboarding.empty.upload'),
    to: '/import',
    path: '/budget',
  },
  transactions: {
    icon: <List {...ICON} />,
    title: t('onboarding.empty.transactions.title'),
    text: t('onboarding.empty.transactions.text'),
    action: t('onboarding.empty.upload'),
    to: '/import',
    path: '/transactions',
  },
  pending: {
    icon: <HandCoins {...ICON} />,
    title: t('onboarding.empty.pending.title'),
    text: t('onboarding.empty.pending.text'),
    action: t('onboarding.empty.toTransactions'),
    to: '/transactions',
    path: '/pending',
  },
  investments: {
    icon: <Sprout {...ICON} />,
    title: t('onboarding.empty.investments.title'),
    text: t('onboarding.empty.investments.text'),
    action: t('onboarding.empty.toTransactions'),
    to: '/transactions',
    path: '/investments',
  },
  recurring: {
    icon: <Repeat {...ICON} />,
    title: t('onboarding.empty.recurring.title'),
    text: t('onboarding.empty.recurring.text'),
    action: t('onboarding.empty.uploadMonth'),
    to: '/import',
    path: '/recurring',
  },
  reports: {
    icon: <ChartColumn {...ICON} />,
    title: t('onboarding.empty.reports.title'),
    text: t('onboarding.empty.reports.text'),
    action: t('onboarding.empty.uploadMonth'),
    to: '/import',
    path: '/reports',
  },
  log: {
    icon: <History {...ICON} />,
    title: t('onboarding.empty.log.title'),
    text: t('onboarding.empty.log.text'),
    action: t('onboarding.empty.toTransactions'),
    to: '/transactions',
    path: '/log',
  },
}

/** Hosted mode: the designed empty state of a view (never a bare "no data"), with its one
 * action and a look at the same view in the demo. */
export function HostedEmpty({ view }: { view: EmptyView }) {
  const mode = useMode()
  const spec = VIEWS[view]
  return (
    <EmptyState
      icon={spec.icon}
      title={spec.title}
      text={spec.text}
      action={{ label: spec.action, to: spec.to }}
      preview={previewUrl(mode.demo_url, spec.path)}
    />
  )
}
