import { describe, expect, it } from 'vitest'
import { type ExtensionStatus, DOWNLOAD_PATH, codeExpiry, linkedLine } from './extension'

const linked: ExtensionStatus = {
  linked: true,
  linked_at: '2026-11-20T15:00:00+00:00',
  last_used_at: null,
  orders: 0,
}

describe('linkedLine', () => {
  it('says when it was linked and that it was never used', () => {
    expect(linkedLine(linked)).toMatch(/^Vinculada el .+\. Aún no ha enviado nombres\.$/) // spanish-ui
  })

  it('says when it was last used and how many orders have names', () => {
    const used = { ...linked, last_used_at: '2026-11-21T10:00:00+00:00', orders: 42 }
    expect(linkedLine(used)).toMatch(/^Vinculada el .+\. Último envío: .+ · 42 pedidos con nombres\.$/) // spanish-ui
  })

  it('is empty when nothing is linked', () => {
    expect(linkedLine({ linked: false, linked_at: null, last_used_at: null, orders: 3 })).toBe('')
  })
})

describe('codeExpiry', () => {
  it('names the local time the code expires', () => {
    expect(codeExpiry('2026-11-20T15:10:00+00:00')).toMatch(/^Vence a las .+\.$/) // spanish-ui
    expect(codeExpiry('nonsense')).toBe('')
  })
})

describe('the download', () => {
  it('is served by the app itself', () => {
    expect(DOWNLOAD_PATH).toBe('/api/extension/download')
  })
})
