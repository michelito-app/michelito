// El mes que se mira en Resumen o Transacciones viaja por el menú, solo en la URL.
import { useEffect } from 'react'
import { useOutletContext } from 'react-router'

/** Pantallas del menú que muestran un mes. */
const MONTH_ROUTES: readonly string[] = ['/', '/transacciones']

/** Lo que `AppShell` da a las pantallas para avisar qué mes se mira. */
export interface NavMonthContext {
  setNavMonth: (month: string | null) => void
}

/** Enlace del menú: Resumen y Transacciones llevan `?mes=` si se mira otro mes que el de por
 * defecto (`month` no nulo). */
export function navHref(to: string, month: string | null): string {
  if (month === null || !MONTH_ROUTES.includes(to)) return to
  return `${to}?${new URLSearchParams({ mes: month })}`
}

/** Avisa al menú del mes que se mira (null si es el de por defecto); al salir, lo quita. */
export function usePublishNavMonth(month: string | null): void {
  const context = useOutletContext<NavMonthContext | undefined>()
  const setNavMonth = context?.setNavMonth
  useEffect(() => {
    if (!setNavMonth) return
    setNavMonth(month)
    return () => setNavMonth(null)
  }, [setNavMonth, month])
}
