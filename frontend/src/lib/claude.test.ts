import { describe, expect, it, vi } from 'vitest'
import { t } from '@/i18n'
import { accountsText, composeForClaude, copyText, dossierPath, hashFrom, pastedBody, sizeText } from '@/lib/claude'

describe('dossierPath', () => {
  it('carries only the month and the accounts', () => {
    expect(dossierPath('2026-02', null)).toBe('/api/dossier?month=2026-02')
    expect(dossierPath('2026-02', ['bhd:1', 'card:2'])).toBe('/api/dossier?month=2026-02&accounts=bhd%3A1%2Ccard%3A2')
  })
})

describe('composeForClaude', () => {
  it('puts the instruction on top and the dossier below', () => {
    expect(composeForClaude('  Analyse.  ', '# Dossier\n')).toBe('Analyse.\n\n---\n\n# Dossier\n')
  })
  it('without an instruction only the dossier goes', () => {
    expect(composeForClaude('   ', '# Dossier')).toBe('# Dossier\n')
  })
})

describe('sizeText', () => {
  it('bytes and words', () => {
    expect(sizeText('hola mundo')).toBe(t('claude.size', { size: '10 B', words: '2' }))
    expect(sizeText('a '.repeat(1024))).toBe('2.0 KB · 1,024 palabras') // spanish-ui
  })
})

describe('copyText', () => {
  it('copies with the clipboard in a secure context', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    expect(await copyText('x', { isSecureContext: true, clipboard: { writeText } })).toBe('copied')
    expect(writeText).toHaveBeenCalledWith('x')
  })
  it('by hand when the browser refuses', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    expect(await copyText('x', { isSecureContext: true, clipboard: { writeText } })).toBe('manual')
  })
  it('by hand without a secure context or a clipboard (without trying)', async () => {
    const writeText = vi.fn()
    expect(await copyText('x', { isSecureContext: false, clipboard: { writeText } })).toBe('manual')
    expect(await copyText('x', { isSecureContext: true })).toBe('manual')
    expect(writeText).not.toHaveBeenCalled()
  })
})

describe('pastedBody', () => {
  it('is a new analysis with the copied accounts', () => {
    expect(pastedBody('Text', null, null)).toEqual({ text: 'Text', fresh: true, accounts: null })
    expect(pastedBody('Text', ['a'], 'abcdef0123456789')).toEqual({
      text: 'Text',
      fresh: true,
      accounts: ['a'],
      fingerprint: 'abcdef0123456789',
    })
  })
})

describe('hashFrom', () => {
  it("takes the header's fingerprint only when it has the expected shape", () => {
    expect(hashFrom(new Headers({ 'X-Michelito-Fingerprint': '0123456789abcdef' }))).toBe('0123456789abcdef')
    expect(hashFrom(new Headers({ 'X-Michelito-Fingerprint': 'something-else' }))).toBeNull()
    expect(hashFrom(new Headers())).toBeNull()
  })
})

describe('accountsText', () => {
  it('all, or the names', () => {
    expect(accountsText(null, new Map())).toBe(t('claude.allAccounts'))
    expect(accountsText(['a', 'b'], new Map([['a', 'Visa']]))).toBe('Visa, b')
  })
})
