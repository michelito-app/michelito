// Loans in the interface (pure logic). The server links the payments and computes
// the schedule (src/michelito/web/loans.py); this only builds texts, the form's bodies and the
// loan's place in the Accounts list.
import { LOCALE, t } from '@/i18n'
import type { Loan, LoanBody, LoanCurrency, LoanDifference, LoanEdit, Tx } from './api'
import { formatMoney, parseCents } from './links'
import { monthPhrase } from './months'

/** Limits the server checks too (src/michelito/migrations_v26.py, analysis/loan_match.py). */
export const NAME_MAX = 80
export const NUMBER_MIN = 5
export const NUMBER_MAX = 40
export const TERM_MAX = 600
const RATE_MAX_BP = 10_000
const BP_PER_PERCENT = 100

const withCents = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** The bank's installment to the cent, as the bank prints it: "RD$ 7,756.66". */
export function installmentText(cents: number, currency: LoanCurrency): string {
  return `${currency === 'USD' ? 'US$' : 'RD$'} ${withCents.format(cents / 100)}`
}

/** A loan in Accounts: `?account=loan-7`. */
const ACCOUNT_PREFIX = 'loan-'

export function loanAccountKey(id: number): string {
  return `${ACCOUNT_PREFIX}${id}`
}

export function loanIdOf(key: string | null): number | null {
  if (key === null || !key.startsWith(ACCOUNT_PREFIX)) return null
  const id = Number(key.slice(ACCOUNT_PREFIX.length))
  return Number.isInteger(id) && id > 0 ? id : null
}

/** What is owed, negative like a card's balance: "−RD$ 75,000". */
export function balanceText(loan: Pick<Loan, 'balance_cents' | 'currency'>): string {
  return formatMoney(-loan.balance_cents, loan.currency)
}

/** The share of the original amount already paid off (0 to 1). */
export function progress(loan: Pick<Loan, 'balance_cents' | 'principal_cents'>): number {
  if (loan.principal_cents <= 0) return 0
  const share = 1 - loan.balance_cents / loan.principal_cents
  return Math.min(1, Math.max(0, share))
}

/** 1250 → "12.5 %". */
export function rateText(bp: number): string {
  return `${Number((bp / BP_PER_PERCENT).toFixed(2))} %`
}

/** "12,5" or "12.5 %" → 1250; null unless it is between 0 and 100 with up to 2 decimals. */
export function parseRate(text: string): number | null {
  const clean = text.trim().replace(/\s*%$/, '').replace(',', '.')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const bp = Math.round(Number(clean) * BP_PER_PERCENT)
  return bp <= RATE_MAX_BP ? bp : null
}

/** "Faltan 9 cuotas · termina en enero 2027" (or "Pagado"). */
export function remainingLine(loan: Pick<Loan, 'installments_left' | 'end_date'>): string {
  if (loan.installments_left === 0 || loan.end_date === null) return t('loans.card.paidOff')
  return t('loans.card.remaining', {
    count: loan.installments_left,
    month: monthPhrase(loan.end_date.slice(0, 7)),
  })
}

/** Interest paid: what the statements say and what the contract estimates for the rest. */
export function interestLine(loan: Loan): string {
  const statements = loan.interest_statements_cents
  const estimated = loan.interest_estimated_cents
  const total = formatMoney(statements + estimated, loan.currency)
  if (statements === 0) return t('loans.card.interestEstimated', { total })
  if (estimated === 0) return t('loans.card.interestStatements', { total })
  return t('loans.card.interestMixed', {
    total,
    statements: formatMoney(statements, loan.currency),
    estimated: formatMoney(estimated, loan.currency),
  })
}

export function differenceText(loan: Pick<Loan, 'currency'>, d: LoanDifference): string {
  return t(`loans.difference.${d.kind}`, {
    month: monthPhrase(d.month),
    expected: formatMoney(d.expected_cents, loan.currency),
    found: formatMoney(d.found_cents, loan.currency),
  })
}

/** A row's line: "loan · Car" (from the catalog); null when it pays no loan. */
export function loanTag(tx: Pick<Tx, 'loan'>): string | null {
  return tx.loan ? t('loans.row.tag', { name: tx.loan.name }) : null
}

/** The loan form, as typed. */
export interface LoanForm {
  name: string
  number: string
  currency: LoanCurrency
  principal: string
  rate: string
  term: string
  start: string
  installment: string // the bank's, from the start ('' = computed from the contract)
}

export function emptyForm(today: string): LoanForm {
  return {
    name: '',
    number: '',
    currency: 'DOP',
    principal: '',
    rate: '',
    term: '',
    start: today,
    installment: '',
  }
}

export function formOf(loan: Loan): LoanForm {
  return {
    name: loan.name,
    number: loan.number,
    currency: loan.currency,
    principal: String(loan.principal_cents / 100),
    rate: String(Number(((loan.rates[0]?.rate_bp ?? loan.rate_bp) / BP_PER_PERCENT).toFixed(2))),
    term: String(loan.term),
    start: loan.start_date,
    installment: startingInstallment(loan)?.toString() ?? '',
  }
}

/** The bank's installment from the start, in money (null: none). */
function startingInstallment(loan: Loan): number | null {
  const found = loan.installments.find((entry) => entry.effective === loan.start_date)
  return found === undefined ? null : found.installment_cents / 100
}

/** The installment field: '' is none, anything else must be an amount above zero. */
function parseInstallment(text: string): { cents: number | null } | null {
  if (text.trim() === '') return { cents: null }
  const cents = parseCents(text)
  return cents === null ? null : { cents }
}

type Result<T> = { error: string; body: null } | { error: null; body: T }

type FormError =
  | 'loans.form.error.name'
  | 'loans.form.error.number'
  | 'loans.form.error.principal'
  | 'loans.form.error.rate'
  | 'loans.form.error.term'
  | 'loans.form.error.start'
  | 'loans.form.error.installment'

function fail<T>(key: FormError): Result<T> {
  return { error: t(key), body: null }
}

function parseTerm(text: string): number | null {
  const term = Number(text.trim())
  return Number.isInteger(term) && term >= 1 && term <= TERM_MAX ? term : null
}

function validNumber(text: string): boolean {
  const clean = text.replace(/[^0-9A-Za-z]/g, '')
  return clean.replace(/^0+/, '') !== '' && clean.length >= NUMBER_MIN && clean.length <= NUMBER_MAX
}

/** "Create loan": every field checked, or what to fix. */
export function loanBody(form: LoanForm): Result<LoanBody> {
  const name = form.name.trim()
  if (name === '' || name.length > NAME_MAX) return fail('loans.form.error.name')
  if (!validNumber(form.number)) return fail('loans.form.error.number')
  const principal = parseCents(form.principal)
  if (principal === null) return fail('loans.form.error.principal')
  const rate = parseRate(form.rate)
  if (rate === null) return fail('loans.form.error.rate')
  const term = parseTerm(form.term)
  if (term === null) return fail('loans.form.error.term')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.start)) return fail('loans.form.error.start')
  const installment = parseInstallment(form.installment)
  if (installment === null) return fail('loans.form.error.installment')
  return {
    error: null,
    body: {
      name,
      number: form.number.trim(),
      currency: form.currency,
      principal_cents: principal,
      rate_bp: rate,
      term,
      start_date: form.start,
      ...(installment.cents === null ? {} : { installment_cents: installment.cents }),
    },
  }
}

/** "Save": only what changed (the rate changes through the rate history). */
export function loanEdit(loan: Loan, form: LoanForm): Result<LoanEdit> {
  const body: LoanEdit = {}
  const name = form.name.trim()
  if (name !== loan.name) {
    if (name === '' || name.length > NAME_MAX) return fail('loans.form.error.name')
    body.name = name
  }
  if (form.number.trim() !== loan.number) {
    if (!validNumber(form.number)) return fail('loans.form.error.number')
    body.number = form.number.trim()
  }
  const principal = parseCents(form.principal)
  if (principal === null) return fail('loans.form.error.principal')
  if (principal !== loan.principal_cents) body.principal_cents = principal
  const term = parseTerm(form.term)
  if (term === null) return fail('loans.form.error.term')
  if (term !== loan.term) body.term = term
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.start)) return fail('loans.form.error.start')
  if (form.start !== loan.start_date) body.start_date = form.start
  const installment = parseInstallment(form.installment)
  if (installment === null) return fail('loans.form.error.installment')
  const before = startingInstallment(loan)
  const beforeCents = before === null ? null : Math.round(before * 100)
  if (installment.cents !== beforeCents) body.installment_cents = installment.cents
  return { error: null, body }
}
