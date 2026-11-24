import { describe, expect, it } from 'vitest'
import { connectionLine, connectorUrl } from './connector'

describe('connector', () => {
  it('builds the address to paste in Claude from the origin', () => {
    expect(connectorUrl('https://app.example')).toBe('https://app.example/api/mcp')
    expect(connectorUrl('https://app.example/')).toBe('https://app.example/api/mcp')
  })

  it('names when a connection was made and last used', () => {
    const line = connectionLine({
      id: 1,
      client_name: 'Claude',
      created_at: '2026-11-20T10:00:00+00:00',
      last_used_at: '2026-11-23T10:00:00+00:00',
    })
    expect(line).toContain('2026')
    expect(line).not.toContain('{')
  })
})
