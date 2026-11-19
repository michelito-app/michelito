// Dinero siempre en centavos enteros (como lo manda la API); aquí solo se formatea.
const MINUS = '−'

const pesos = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const dollars = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function wholePesos(cents: number): string {
  return pesos.format(Math.abs(cents) / 100)
}

/** RD$ sin decimales y con separador de miles: "RD$ 148,320". */
export function formatDop(cents: number): string {
  const sign = cents < 0 && wholePesos(cents) !== '0' ? MINUS : ''
  return `${sign}RD$ ${wholePesos(cents)}`
}

/** Pesos sin prefijo, para columnas que ya dicen RD$: "34,200", "−500". */
export function formatPesos(cents: number): string {
  const amount = wholePesos(cents)
  return cents < 0 && amount !== '0' ? `${MINUS}${amount}` : amount
}

/** Diferencia en RD$ con signo explícito: "+RD$ 11,500", "−RD$ 2,550", "RD$ 0". */
export function formatSignedDop(cents: number): string {
  const amount = wholePesos(cents)
  if (amount === '0') return 'RD$ 0'
  return `${cents < 0 ? MINUS : '+'}RD$ ${amount}`
}

/** US$ con dos decimales: "US$ 11.99". */
export function formatUsd(cents: number): string {
  const sign = cents < 0 ? MINUS : ''
  return `${sign}US$ ${dollars.format(Math.abs(cents) / 100)}`
}
