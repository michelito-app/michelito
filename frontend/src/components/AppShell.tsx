import {
  ChartColumn,
  FileUp,
  FlaskConical,
  HandCoins,
  History,
  Lock,
  PiggyBank,
  Repeat,
  Sprout,
  Tags,
  Users,
} from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { DemoBanner } from '@/components/demo/DemoBanner'
import { countVisit, isDemo, productName, useMode } from '@/lib/demo'
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

const NAV: { to: string; label: string; icon: ReactNode }[] = [
  {
    to: '/',
    label: 'Resumen',
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
    to: '/presupuesto',
    label: 'Presupuesto',
    icon: <PiggyBank size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/transacciones',
    label: 'Transacciones',
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
    to: '/pendientes',
    label: 'Pendientes',
    icon: <HandCoins size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/compartidos',
    label: 'Compartidos',
    icon: <Users size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/inversiones',
    label: 'Inversiones',
    icon: <Sprout size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/recurrentes',
    label: 'Recurrentes',
    icon: <Repeat size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/reportes',
    label: 'Reportes',
    icon: <ChartColumn size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/cuentas',
    label: 'Cuentas',
    icon: (
      <svg {...ICON}>
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <path d="M2 10h20M6 15h4" />
      </svg>
    ),
  },
  {
    to: '/categorias',
    label: 'Categorías',
    icon: <Tags size={18} strokeWidth={2} aria-hidden="true" />,
  },
  {
    to: '/bitacora',
    label: 'Bitácora',
    icon: <History size={18} strokeWidth={2} aria-hidden="true" />,
  },
]

// Solo en la demo: el estado de ejemplo (en local se importa con `finanzas importar`).
const IMPORT_NAV = {
  to: '/importar',
  label: 'Importar',
  icon: <FileUp size={18} strokeWidth={2} aria-hidden="true" />,
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

/** Barra lateral + contenido; en pantallas de teléfono la barra pasa arriba. Mientras Resumen o
 * Transacciones miran otro mes que el de por defecto, sus enlaces lo llevan (`?mes=`). */
export function AppShell() {
  const [navMonth, setNavMonth] = useState<string | null>(null)
  // Estable: cambiar el mes del menú no vuelve a renderizar la página.
  const context = useMemo<NavMonthContext>(() => ({ setNavMonth }), [])
  const mode = useMode()
  const demo = isDemo(mode)
  const { pathname } = useLocation()
  useEffect(() => {
    if (demo) countVisit(pathname)
  }, [demo, pathname])
  const nav = demo ? [...NAV, IMPORT_NAV] : NAV
  const shell = (
    <div className={cn('flex flex-wrap items-stretch', demo ? 'flex-1' : 'min-h-screen')}>
      <nav
        aria-label="Principal"
        className="flex max-w-full flex-[1_1_232px] flex-col gap-1 border-r border-border bg-card px-4 py-6"
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
          {demo ? (
            <>
              <FlaskConical size={14} aria-hidden="true" />
              Demo pública
            </>
          ) : (
            <>
              <Lock size={14} aria-hidden="true" />
              Solo en esta máquina
            </>
          )}
        </div>
      </nav>
      <main className="flex min-w-0 flex-[999_1_560px] flex-col gap-6 px-4 pt-6 pb-12 sm:px-10 sm:pt-8">
        <Outlet context={context} />
      </main>
    </div>
  )
  if (!demo) return shell
  // En la demo, la cabecera del aviso va arriba de todo y el resto ocupa lo que queda.
  return (
    <div className="flex min-h-screen flex-col">
      <DemoBanner />
      {shell}
    </div>
  )
}
