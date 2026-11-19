// Account selection for Summary and Recurring: the URL (`accounts`) wins; without it, the remembered one.
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
  /** false while the accounts load and there is a selection to validate against them. */
  ready: boolean
  select: (next: Selection) => void
}

const NONE: readonly AccountRef[] = []

/** Copy of `params` with the selection set (or removed with "All"). */
export function paramsWithSelection(params: URLSearchParams, next: Selection): URLSearchParams {
  const copy = new URLSearchParams(params)
  copy.delete(LEGACY_ACCOUNT_PARAM)
  const text = selectionParam(next)
  if (text === null) copy.delete(ACCOUNTS_PARAM)
  else copy.set(ACCOUNTS_PARAM, text)
  return copy
}

/** A valid selection arriving through the URL is remembered (once the accounts loaded), so the
 * menu takes the same accounts to the other screens. */
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

/** Account selection for Summary and Recurring. */
export function useAccountSelection(): AccountSelection {
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const raw = selectionFromParams(params)
  const stored = readStored()
  const pending = accounts.isPending && (raw !== null || stored !== null)
  // If the accounts fail to load, everything is shown: better than an empty screen.
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
