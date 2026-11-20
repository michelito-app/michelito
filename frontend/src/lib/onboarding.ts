// Hosted onboarding (src/michelito/hosted/onboarding_routes.py): the gate, uploads and their
// processing, the first review and the setup checklist. The pure logic is kept apart from the
// calls. A PDF password only ever travels in a POST body and is never kept here.
import { useQuery } from '@tanstack/react-query'
import { t } from '@/i18n'
import { request } from '@/lib/api'
import { monthPhrase } from '@/lib/months'

export const MAX_FILES = 12
export const MAX_FILE_MB = 8
export const POLL_MS = 600
export const SUPPORTED_BANKS = ['popular', 'bhd', 'banreservas'] as const
export const REQUESTABLE_BANKS = [
  'scotiabank',
  'santa_cruz',
  'apap',
  'cibao',
  'banesco',
  'promerica',
  'bdi',
  'caribe',
  'vimenca',
  'lafise',
  'ademi',
  'lopez_de_haro',
  'other',
] as const
const SHARE = /^#share=([A-Za-z0-9_-]{16,64})$/

export type SupportedBank = (typeof SUPPORTED_BANKS)[number]
export type RequestableBank = (typeof REQUESTABLE_BANKS)[number]
export type FileStateName =
  | 'queued'
  | 'reading'
  | 'squared'
  | 'duplicate'
  | 'invalid'
  | 'locked'
  | 'unsupported'
  | 'unreadable'
  | 'too_complex'

export interface StatementRead {
  bank: string
  kind: string
  identifier: string
  month: string
  transactions: number
}

export interface UploadFile {
  id: number
  name: string
  state: FileStateName
  bank: string | null
  reads: StatementRead[]
}

/** The last password try: which bank, how many files it opened, how many stay locked. */
export interface PasswordTry {
  bank: string
  opened: number
  left: number
}

export interface Job {
  id: string
  files: UploadFile[]
  done: boolean
  squared: number
  misses: string[]
  last_try: PasswordTry | null
}

export interface Missing {
  bank: string
  kind: string
  identifier: string
  month: string
}

export interface Checklist {
  months: number
  accounts: number
  more_months_done: boolean
  other_account_done: boolean
  missing: Missing[]
  visible: boolean
}

export interface Onboarding {
  open: boolean
  landing: string | null
  checklist: Checklist
  first_review: boolean
}

export interface Merchant {
  merchant: string
  total: string // RD$ with two decimals
  count: number
  category: string
  category_id: number | null
  fingerprint: string
  status: 'pending' | 'reviewed' | 'rule'
}

export type Flag = 'first_review_closed' | 'checklist_dismissed'

const BANK_KEYS = {
  popular: 'onboarding.bank.popular',
  bhd: 'onboarding.bank.bhd',
  banreservas: 'onboarding.bank.banreservas',
  scotiabank: 'onboarding.bank.scotiabank',
  santa_cruz: 'onboarding.bank.santa_cruz',
  apap: 'onboarding.bank.apap',
  cibao: 'onboarding.bank.cibao',
  banesco: 'onboarding.bank.banesco',
  promerica: 'onboarding.bank.promerica',
  bdi: 'onboarding.bank.bdi',
  caribe: 'onboarding.bank.caribe',
  vimenca: 'onboarding.bank.vimenca',
  lafise: 'onboarding.bank.lafise',
  ademi: 'onboarding.bank.ademi',
  lopez_de_haro: 'onboarding.bank.lopez_de_haro',
  other: 'onboarding.bank.other',
} as const

/** The bank's visible name (the key itself if it is not one we know). */
export function bankName(bank: string): string {
  return bank in BANK_KEYS ? t(BANK_KEYS[bank as keyof typeof BANK_KEYS]) : bank
}

/** The masked account: a card or another account, with its last four characters. */
export function accountMask(kind: string, identifier: string): string {
  return kind === 'credit_card'
    ? t('onboarding.account.card', { last4: identifier })
    : t('onboarding.account.other', { last4: identifier })
}

/** What a finished file says about itself: bank · account · month · N transactions. */
export function readLine(read: StatementRead): string {
  return [
    bankName(read.bank),
    accountMask(read.kind, read.identifier),
    monthPhrase(read.month),
    t('common.transactions', { count: read.transactions }),
  ].join(' · ')
}

const STATE_KEYS = {
  queued: 'onboarding.file.queued',
  reading: 'onboarding.file.reading',
  squared: 'onboarding.file.squared',
  duplicate: 'onboarding.file.duplicate',
  invalid: 'onboarding.file.invalid',
  locked: 'onboarding.file.locked',
  unsupported: 'onboarding.file.unsupported',
  unreadable: 'onboarding.file.unreadable',
  too_complex: 'onboarding.file.tooComplex',
} as const

export function stateText(state: FileStateName): string {
  return t(STATE_KEYS[state])
}

export function opened(file: UploadFile): boolean {
  return file.state === 'squared' || file.state === 'duplicate'
}

export function failed(file: UploadFile): boolean {
  return ['invalid', 'unsupported', 'unreadable', 'too_complex'].includes(file.state)
}

export function lockedFiles(job: Job): UploadFile[] {
  return job.files.filter((file) => file.state === 'locked')
}

/** Every file has its final answer and none opened (locked ones count as not opened). */
export function noneSquared(job: Job): boolean {
  return job.squared === 0 && job.files.every((f) => f.state !== 'queued' && f.state !== 'reading')
}

/** Why these files cannot be sent as they are (null: they can). */
export function filesProblem(files: readonly File[]): string | null {
  if (files.length > MAX_FILES) return t('onboarding.upload.tooMany', { count: MAX_FILES })
  for (const file of files) {
    const pdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    if (!pdf) return t('onboarding.upload.notPdf', { name: file.name })
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      return t('onboarding.upload.tooLarge', { name: file.name, megabytes: MAX_FILE_MB })
    }
  }
  return null
}

/** Base64 of the bytes (for the JSON body of the upload). */
export function toBase64(bytes: Uint8Array): string {
  let text = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    text += String.fromCharCode(...bytes.subarray(i, i + step))
  }
  return btoa(text)
}

/** The share-target token in the URL fragment (`#share=…`), if well formed. */
export function shareToken(hash: string): string | null {
  return SHARE.exec(hash)?.[1] ?? null
}

/** Takes the share token out of the address at once and returns it. */
export function takeShareToken(): string | null {
  const { hash, pathname, search } = window.location
  if (!hash.startsWith('#share=')) return null
  window.history.replaceState(window.history.state, '', pathname + search)
  return shareToken(hash)
}

/** One missing month of one account, as a checklist line. */
export function missingLine(missing: Missing): string {
  return t('onboarding.checklist.missing', {
    month: monthPhrase(missing.month),
    bank: bankName(missing.bank),
    account: accountMask(missing.kind, missing.identifier),
  })
}

/** The demo's address for one view ("see how it looks"). */
export function previewUrl(demoUrl: string | undefined, path: string): string | null {
  if (!demoUrl) return null
  return `${demoUrl.replace(/\/$/, '')}${path}`
}

export const onboardingKey = ['onboarding'] as const
export const merchantsKey = ['onboarding', 'merchants'] as const

export function useOnboarding(enabled = true) {
  return useQuery({
    queryKey: onboardingKey,
    queryFn: () => request<Onboarding>('/api/onboarding'),
    enabled,
  })
}

export function useMerchants(enabled = true) {
  return useQuery({
    queryKey: merchantsKey,
    queryFn: () => request<Merchant[]>('/api/onboarding/merchants'),
    enabled,
  })
}

export async function startUpload(files: readonly File[]): Promise<Job> {
  const encoded = await Promise.all(
    files.map(async (file) => ({
      name: file.name,
      data: toBase64(new Uint8Array(await file.arrayBuffer())),
    })),
  )
  return request<Job>('/api/uploads', { method: 'POST', body: JSON.stringify({ files: encoded }) })
}

export function fetchJob(id: string): Promise<Job> {
  return request<Job>(`/api/uploads/${encodeURIComponent(id)}`)
}

export function fetchLatestJob(): Promise<Job | null> {
  return request<Job | null>('/api/uploads/latest')
}

export function tryPassword(id: string, bank: SupportedBank, password: string): Promise<Job> {
  return request<Job>(`/api/uploads/${encodeURIComponent(id)}/password`, {
    method: 'POST',
    body: JSON.stringify({ bank, password }),
  })
}

export interface SharedFile {
  name: string
  size: number
}

/** What was shared (names and sizes), without importing it. */
export function peekShare(token: string): Promise<SharedFile[]> {
  return request<SharedFile[]>('/api/uploads/shared/peek', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

export async function discardShare(token: string): Promise<void> {
  await request('/api/uploads/shared/discard', { method: 'POST', body: JSON.stringify({ token }) })
}

/** The explicit "Import" of a share. */
export function claimShare(token: string): Promise<Job> {
  return request<Job>('/api/uploads/shared', { method: 'POST', body: JSON.stringify({ token }) })
}

export async function requestBank(bank: RequestableBank): Promise<void> {
  await request('/api/banks/requests', { method: 'POST', body: JSON.stringify({ bank }) })
}

export function reviewMerchant(merchant: string): Promise<Merchant[]> {
  return request<Merchant[]>('/api/onboarding/merchants/review', {
    method: 'PUT',
    body: JSON.stringify({ merchant }),
  })
}

export async function setFlag(flag: Flag): Promise<void> {
  await request(`/api/onboarding/flags/${flag}`, { method: 'PUT' })
}
