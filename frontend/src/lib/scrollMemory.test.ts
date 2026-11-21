import { describe, expect, it } from 'vitest'
import { parseKeys, parsePosition, withKey } from './scrollMemory'

describe('stored scroll position', () => {
  it('reads a non-negative number and ignores anything else', () => {
    expect(parsePosition('420')).toBe(420)
    expect(parsePosition('0')).toBe(0)
    expect(parsePosition(null)).toBeNull()
    expect(parsePosition('-3')).toBeNull()
    expect(parsePosition('abc')).toBeNull()
  })
})

describe('remembered entries', () => {
  it('moves a written key to the end and forgets the oldest past the cap', () => {
    expect(withKey(['a', 'b', 'c'], 'a', 3)).toEqual({ keys: ['b', 'c', 'a'], dropped: [] })
    expect(withKey(['a', 'b', 'c'], 'd', 3)).toEqual({ keys: ['b', 'c', 'd'], dropped: ['a'] })
  })

  it('reads only a list of strings', () => {
    expect(parseKeys('["a",1,"b"]')).toEqual(['a', 'b'])
    expect(parseKeys('{}')).toEqual([])
    expect(parseKeys('nope')).toEqual([])
    expect(parseKeys(null)).toEqual([])
  })
})
