// Money is always in whole cents (as the API sends it); this only formats it.
import { LOCALE } from '@/i18n'

const MINUS = '−'

const wholeUnits = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 })
const dollars = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function wholeDop(cents: number): string {
  return wholeUnits.format(Math.abs(cents) / 100)
}

/** RD$ without decimals and with a thousands separator: "RD$ 148,320". */
export function formatDop(cents: number): string {
  const sign = cents < 0 && wholeDop(cents) !== '0' ? MINUS : ''
  return `${sign}RD$ ${wholeDop(cents)}`
}

/** RD$ amount without the prefix, for columns that already say RD$: "34,200", "−500". */
export function formatDopNumber(cents: number): string {
  const amount = wholeDop(cents)
  return cents < 0 && amount !== '0' ? `${MINUS}${amount}` : amount
}

/** A difference in RD$ with an explicit sign: "+RD$ 11,500", "−RD$ 2,550", "RD$ 0". */
export function formatSignedDop(cents: number): string {
  const amount = wholeDop(cents)
  if (amount === '0') return 'RD$ 0'
  return `${cents < 0 ? MINUS : '+'}RD$ ${amount}`
}

/** US$ with two decimals: "US$ 11.99". */
export function formatUsd(cents: number): string {
  const sign = cents < 0 ? MINUS : ''
  return `${sign}US$ ${dollars.format(Math.abs(cents) / 100)}`
}
