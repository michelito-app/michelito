import { describe, expect, it } from 'vitest'
import {
  type Job,
  MAX_FILES,
  accountMask,
  bankName,
  failed,
  filesProblem,
  lockedFiles,
  missingLine,
  noneSquared,
  previewUrl,
  readLine,
  shareToken,
  stateText,
  toBase64,
} from './onboarding'

function job(states: Job['files'][number]['state'][], squared = 0): Job {
  return {
    id: 'j',
    files: states.map((state, index) => ({ id: index, name: `${index}.pdf`, state, bank: null, reads: [] })),
    done: states.every((s) => s !== 'queued' && s !== 'reading'),
    squared,
    misses: [],
    last_try: null,
  }
}

function pdf(name: string, size = 10, type = 'application/pdf'): File {
  return new File([new Uint8Array(size)], name, { type })
}

describe('what a file says', () => {
  it('names the bank, the masked account, the month and the transactions', () => {
    const line = readLine({
      bank: 'bhd',
      kind: 'credit_card',
      identifier: '4242',
      month: '2026-10',
      transactions: 43,
    })
    expect(line).toBe('BHD · Tarjeta ···4242 · octubre 2026 · 43 transacciones') // spanish-ui
    expect(accountMask('savings', '4242')).toBe('Cuenta ···4242') // spanish-ui
    expect(bankName('unknown-bank')).toBe('unknown-bank')
    expect(stateText('squared')).toBe('✓ cuadró al centavo') // spanish-ui
  })

  it('says a loan history in payments, and when its loan is missing', () => {
    const line = readLine({
      bank: 'popular',
      kind: 'loan',
      identifier: '4567',
      month: '2025-06',
      transactions: 5,
    })
    expect(line).toBe('Popular · Préstamo ···4567 · junio 2025 · 5 pagos') // spanish-ui
    expect(stateText('no_loan')).toContain('préstamo') // spanish-ui
    expect(failed({ id: 1, name: 'loan.pdf', state: 'no_loan', bank: 'popular', reads: [] })).toBe(
      true,
    )
  })

  it('lists a missing month like the report', () => {
    expect(
      missingLine({ bank: 'bhd', kind: 'credit_card', identifier: '4242', month: '2026-10' }),
    ).toBe('Te falta octubre 2026 de BHD Tarjeta ···4242') // spanish-ui
  })
})

describe('the job', () => {
  it('knows when nothing squared and what is locked', () => {
    expect(noneSquared(job(['invalid', 'unsupported']))).toBe(true)
    expect(noneSquared(job(['invalid', 'reading']))).toBe(false)
    expect(noneSquared(job(['squared'], 1))).toBe(false)
    expect(lockedFiles(job(['locked', 'squared'], 1))).toHaveLength(1)
  })
})

describe('choosing files', () => {
  it('refuses what is not a PDF, too big or too many', () => {
    expect(filesProblem([pdf('a.pdf')])).toBeNull()
    expect(filesProblem([pdf('a.PDF', 10, '')])).toBeNull()
    expect(filesProblem([pdf('a.jpg', 10, 'image/jpeg')])).toContain('a.jpg')
    expect(filesProblem([pdf('big.pdf', 9 * 1024 * 1024)])).toContain('big.pdf')
    expect(filesProblem(Array.from({ length: MAX_FILES + 1 }, (_, i) => pdf(`${i}.pdf`)))).not.toBeNull()
  })

  it('encodes bytes in base64', () => {
    expect(toBase64(new Uint8Array([37, 80, 68, 70]))).toBe('JVBERg==')
    expect(toBase64(new Uint8Array(100_000)).length).toBe(133_336)
  })
})

describe('links', () => {
  it('reads only a well-formed share token', () => {
    expect(shareToken('#share=abcdefghijklmnopqrstuvwx')).toBe('abcdefghijklmnopqrstuvwx')
    expect(shareToken('#share=short')).toBeNull()
    expect(shareToken('#share=<script>')).toBeNull()
  })

  it('points "see how it looks" at the same view in the demo', () => {
    expect(previewUrl('https://demo.example/', '/recurring')).toBe('https://demo.example/recurring')
    expect(previewUrl(undefined, '/')).toBeNull()
  })
})
