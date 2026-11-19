// Selección de cuentas del Resumen y de Recurrentes: la URL (`cuentas`) gana; si no trae, la recordada.
import { useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router'
import {
  ACCOUNTS_PARAM,
  type AccountRef,
  LEGACY_ACCOUNT_PARAM,
  readStored,
  resolveSelection,
  type Selection,
  selectionFromParams,
  selectionParam,
  storedUpdate,
  writeStored,
} from './accountFilter'
import { useAccounts } from './queries'

export interface AccountSelection {
  selection: Selection
  accounts: readonly AccountRef[]
  /** false mientras cargan las cuentas y hay una selección que validar contra ellas. */
  ready: boolean
  select: (next: Selection) => void
}

const NONE: readonly AccountRef[] = []

/** Copia de `params` con la selección puesta (o quitada con "Todas"). */
export function paramsWithSelection(params: URLSearchParams, next: Selection): URLSearchParams {
  const copy = new URLSearchParams(params)
  copy.delete(LEGACY_ACCOUNT_PARAM)
  const text = selectionParam(next)
  if (text === null) copy.delete(ACCOUNTS_PARAM)
  else copy.set(ACCOUNTS_PARAM, text)
  return copy
}

/** Una selección válida que llega por la URL se recuerda (cuando ya cargaron las cuentas), así
 * el menú lleva a las otras pantallas con las mismas cuentas. */
export function usePersistUrlSelection(
  fromUrl: readonly string[] | null,
  stored: string | null,
  accounts: readonly AccountRef[] | undefined,
): void {
  const update = storedUpdate(fromUrl, stored, accounts)
  const key = update === undefined ? undefined : (selectionParam(update) ?? '')
  useEffect(() => {
    if (key === undefined) return
    writeStored(key === '' ? null : key.split(','))
  }, [key])
}

/** Selección de cuentas del Resumen y de Recurrentes. */
export function useAccountSelection(): AccountSelection {
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const raw = selectionFromParams(params)
  const stored = readStored()
  const pending = accounts.isPending && (raw !== null || stored !== null)
  // Si las cuentas no cargan, se ve todo: mejor que una pantalla vacía.
  const selection = accounts.isError ? null : resolveSelection(raw, stored, accounts.data)
  usePersistUrlSelection(raw, stored, accounts.data)
  const select = useCallback(
    (next: Selection) => {
      writeStored(next)
      setParams((current) => paramsWithSelection(current, next))
    },
    [setParams],
  )
  return { selection, accounts: accounts.data ?? NONE, ready: !pending, select }
}
