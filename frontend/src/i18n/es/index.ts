// The Spanish (es) catalog: the default and, for now, only locale. One module per area;
// every key starts with its module's prefix (checked in i18n.test.ts).
import { common } from './common'
import { shell } from './shell'
import { months } from './months'
import { summary } from './summary'
import { home } from './home'
import { reports } from './reports'
import { transactions } from './transactions'
import { links } from './links'
import { budget } from './budget'
import { cashBox } from './cashBox'
import { investments } from './investments'
import { shared } from './shared'
import { pending } from './pending'
import { review } from './review'
import { accounts } from './accounts'
import { categories } from './categories'
import { recurring } from './recurring'
import { log } from './log'
import { claude } from './claude'
import { demo } from './demo'
import { importing } from './importing'
import { auth } from './auth'
import { onboarding } from './onboarding'
import { forwarding } from './forwarding'
import { receipts } from './receipts'

/** Each area's messages, by key prefix. */
export const AREAS = {
  common,
  shell,
  months,
  summary,
  home,
  reports,
  transactions,
  links,
  budget,
  cashBox,
  investments,
  shared,
  pending,
  review,
  accounts,
  categories,
  recurring,
  log,
  claude,
  demo,
  import: importing,
  auth,
  onboarding,
  forwarding,
  receipts,
} as const

export const es = {
  ...common,
  ...shell,
  ...months,
  ...summary,
  ...home,
  ...reports,
  ...transactions,
  ...links,
  ...budget,
  ...cashBox,
  ...investments,
  ...shared,
  ...pending,
  ...review,
  ...accounts,
  ...categories,
  ...recurring,
  ...log,
  ...claude,
  ...demo,
  ...importing,
  ...auth,
  ...onboarding,
  ...forwarding,
  ...receipts,
} as const
