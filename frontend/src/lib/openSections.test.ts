import { describe, expect, it } from 'vitest'
import { parseOpen, withSection } from './openSections'

describe('parseOpen', () => {
  it('reads a list of ids and ignores anything else', () => {
    expect(parseOpen(null)).toEqual([])
    expect(parseOpen('not json')).toEqual([])
    expect(parseOpen('{"a":1}')).toEqual([])
    expect(parseOpen('["reading", 3, "details"]')).toEqual(['reading', 'details'])
  })
})

describe('withSection', () => {
  it('adds once and removes', () => {
    expect(withSection(['a'], 'b', true)).toEqual(['a', 'b'])
    expect(withSection(['a', 'b'], 'b', true)).toEqual(['a', 'b'])
    expect(withSection(['a', 'b'], 'a', false)).toEqual(['b'])
  })
})
