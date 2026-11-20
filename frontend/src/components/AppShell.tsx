import {
  ChartColumn,
  Ellipsis,
  FileUp,
  FlaskConical,
  HandCoins,
  History,
  Lock,
  PiggyBank,
  Repeat,
  Settings,
  Sprout,
  Tags,
  Users,
} from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { DemoBanner } from '@/components/demo/DemoBanner'
import { SampleBand } from '@/components/onboarding/SampleBand'
import { FOCUS } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import { countVisit, isDemo, isHosted, productName, useMode } from '@/lib/demo'
import { type NavMonthContext, navHref } from '@/lib/navMonth'
import { cn } from '@/lib/utils'

const ICON = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
} as const

interface NavItem {
  to: string
  label: string
  icon: ReactNode
}

const NAV: NavItem[] = [
  {
    to: '/',
    label: t('shell.nav.summary'),
    icon: (
      <svg {...ICON}>
        <rect x="3" y="3" width="7" height="9" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
        <rect x="3" y="16" width="7" height="5" rx="1.5" />
      </svg>
    ),
  },
  {
    to: '/budget',
    label: t('shell.nav.budget'),
    icon: <PiggyBank size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/transactions',
    label: t('shell.nav.transactions'),
    icon: (
      <svg {...ICON}>
        <path d="M8 6h13M8 12h13M8 18h13" />
        <circle cx="4" cy="6" r="1" />
        <circle cx="4" cy="12" r="1" />
        <circle cx="4" cy="18" r="1" />
      </svg>
    ),
  },
  {
    to: '/pending',
    label: t('shell.nav.pending'),
    icon: <HandCoins size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/shared',
    label: t('shell.nav.shared'),
    icon: <Users size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/investments',
    label: t('shell.nav.investments'),
    icon: <Sprout size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/recurring',
    label: t('shell.nav.recurring'),
    icon: <Repeat size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/reports',
    label: t('shell.nav.reports'),
    icon: <ChartColumn size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/accounts',
    label: t('shell.nav.accounts'),
    icon: (
      <svg {...ICON}>
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <path d="M2 10h20M6 15h4" />
      </svg>
    ),
  },
  {
    to: '/categories',
    label: t('shell.nav.categories'),
    icon: <Tags size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/log',
    label: t('shell.nav.log'),
    icon: <History size={18} strokeWidth={2} aria-hidden="true" />,
  },
]

// In the demo, the sample statement (locally it is imported with `michelito import`); in hosted
// mode, uploading statements (the same screen as the gate).
const IMPORT_NAV: NavItem = {
  to: '/import',
  label: t('shell.nav.import'),
  icon: <FileUp size={18} strokeWidth={2} aria-hidden="true" />,
}

// Only in hosted mode: the account and its devices.
const SETTINGS_NAV: NavItem = {
  to: '/settings',
  label: t('auth.shell.settings'),
  icon: <Settings size={18} strokeWidth={2} aria-hidden="true" />,
}

/** The footnote under the menu: where the data lives in each mode. */
function ModeNote({ demo, hosted }: { demo: boolean; hosted: boolean }) {
  if (demo) {
    return (
      <>
        <FlaskConical size={14} aria-hidden="true" />
        {t('shell.publicDemo')}
      </>
    )
  }
  return (
    <>
      <Lock size={14} aria-hidden="true" />
      {hosted ? t('auth.shell.signedIn') : t('shell.localOnly')}
    </>
  )
}

function Logo({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-2.5 px-3 pt-1 pb-6">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <rect width="28" height="28" rx="8" fill="#1F6F5C" />
        <path
          d="M8 18l5-6 4 3 4-6"
          stroke="#FFFFFF"
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-[17px] font-bold tracking-tight">{name}</span>
    </div>
  )
}

/** The phone's bottom bar: these four, then "More" with the rest. */
const BAR_PATHS = ['/', '/transactions', '/shared', '/investments']
const BAR_LABELS: Record<string, string> = {
  '/transactions': t('shell.nav.barTransactions'),
}

/** Sidebar + content; on phones (below `md`) a bottom bar replaces the sidebar. While Summary or Transactions
 * look at a month other than the default one, their links carry it (`?month=`). */
export function AppShell() {
  const [navMonth, setNavMonth] = useState<string | null>(null)
  // Stable: changing the menu's month does not re-render the page.
  const context = useMemo<NavMonthContext>(() => ({ setNavMonth }), [])
  const mode = useMode()
  const demo = isDemo(mode)
  const { pathname } = useLocation()
  useEffect(() => {
    if (demo) countVisit(pathname)
  }, [demo, pathname])
  const hosted = isHosted(mode)
  const nav = demo ? [...NAV, IMPORT_NAV] : hosted ? [...NAV, IMPORT_NAV, SETTINGS_NAV] : NAV
  const shell = (
    <div className={cn('flex flex-wrap items-stretch', demo ? 'flex-1' : 'min-h-screen')}>
      <nav
        aria-label={t('shell.nav.label')}
        className="flex max-w-full max-md:hidden flex-[1_1_232px] flex-col gap-1 border-r border-border bg-card px-4 py-6"
      >
        <Logo name={productName(mode)} />
        {nav.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={navHref(to, navMonth)}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex min-h-11 items-center gap-3 rounded-[10px] px-3 text-sm no-underline',
                isActive
                  ? 'bg-secondary font-semibold text-secondary-foreground'
                  : 'font-medium text-ink-2 hover:bg-muted',
              )
            }
          >
            {icon}
            {label}
          </NavLink>
        ))}
        <div className="mt-auto flex items-center gap-2 px-3 pt-4 text-xs text-muted-foreground">
          <ModeNote demo={demo} hosted={hosted} />
        </div>
      </nav>
      <main className="flex min-w-0 flex-[999_1_560px] flex-col gap-6 px-4 pt-6 pb-12 max-md:pb-[calc(var(--bottom-bar)+env(safe-area-inset-bottom)+1.5rem)] sm:px-10 sm:pt-8">
        <Outlet context={context} />
      </main>
      <BottomBar nav={nav} navMonth={navMonth} demo={demo} hosted={hosted} />
    </div>
  )
  if (!demo) return shell
  // In the demo the notice header goes on top of everything and the rest fills what is left.
  return (
    <div className="flex min-h-screen flex-col">
      {mode.return_url && <SampleBand returnUrl={mode.return_url} />}
      <DemoBanner />
      {shell}
    </div>
  )
}

interface BottomBarProps {
  nav: NavItem[]
  navMonth: string | null
  demo: boolean
  hosted: boolean
}

const BAR_ITEM =
  'flex min-h-11 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[10px] px-0.5 text-[10.5px] leading-tight tracking-tight no-underline'

/** Phone navigation, fixed at the bottom (above the home indicator): Summary, Transactions,
 * Shared, Investments and "More", a sheet with the other sections. */
function BottomBar({ nav, navMonth, demo, hosted }: BottomBarProps) {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const main = nav.filter((item) => BAR_PATHS.includes(item.to))
  const rest = nav.filter((item) => !BAR_PATHS.includes(item.to))
  const inRest = rest.some((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
  return (
    <>
      <nav
        aria-label={t('shell.nav.label')}
        data-bottom-bar=""
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        <ul className="flex h-[calc(var(--bottom-bar)-1px)] items-stretch gap-1 px-1.5 py-1.5">
          {main.map(({ to, label, icon }) => (
            <li key={to} className="flex min-w-0 flex-1">
              <NavLink
                to={navHref(to, navMonth)}
                end={to === '/'}
                className={({ isActive }) =>
                  cn(
                    BAR_ITEM,
                    FOCUS,
                    isActive
                      ? 'bg-secondary font-semibold text-secondary-foreground'
                      : 'font-medium text-ink-2',
                  )
                }
              >
                {icon}
                <span className="max-w-full truncate">{BAR_LABELS[to] ?? label}</span>
              </NavLink>
            </li>
          ))}
          <li className="flex min-w-0 flex-1">
            <button
              type="button"
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-current={inRest ? 'page' : undefined}
              onClick={() => setOpen(true)}
              className={cn(
                BAR_ITEM,
                FOCUS,
                'w-full cursor-pointer',
                inRest
                  ? 'bg-secondary font-semibold text-secondary-foreground'
                  : 'font-medium text-ink-2',
              )}
            >
              <Ellipsis size={18} strokeWidth={2} aria-hidden="true" />
              <span className="max-w-full truncate">{t('shell.nav.more')}</span>
            </button>
          </li>
        </ul>
      </nav>
      {open && (
        <BottomSheet title={t('shell.nav.moreTitle')} onClose={() => setOpen(false)}>
          <ul className="grid grid-cols-2 gap-1.5">
            {rest.map(({ to, label, icon }) => (
              <li key={to} className="flex min-w-0">
                <NavLink
                  to={navHref(to, navMonth)}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      'flex min-h-11 w-full min-w-0 items-center gap-3 rounded-[10px] border border-border px-3 text-sm no-underline',
                      FOCUS,
                      isActive
                        ? 'bg-secondary font-semibold text-secondary-foreground'
                        : 'font-medium text-ink-2',
                    )
                  }
                >
                  {icon}
                  <span className="truncate">{label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <ModeNote demo={demo} hosted={hosted} />
          </p>
        </BottomSheet>
      )}
    </>
  )
}
