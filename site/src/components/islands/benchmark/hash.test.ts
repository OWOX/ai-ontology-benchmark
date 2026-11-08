import { describe, expect, it } from 'vitest'
import { parseHash, serializeHash } from './hash'

describe('benchmark hash', () => {
  it('round-trips every key', () => {
    const s = { puzzle: '3x3', providers: ['anthropic', 'openai'], models: ['claude-opus-5-5', 'gpt-6-luna'], metric: 'hallucination' }
    expect(serializeHash(s)).toBe('#puzzle=3x3&providers=anthropic,openai&models=claude-opus-5-5,gpt-6-luna&metric=hallucination')
    expect(parseHash(serializeHash(s))).toEqual(s)
  })

  it('omits absent keys, and writes nothing at all for the default state', () => {
    expect(serializeHash({})).toBe('')
    expect(serializeHash({ metric: 'detection' })).toBe('#metric=detection')
  })

  it('keeps an empty list apart from an absent one', () => {
    expect(serializeHash({ providers: [] })).toBe('#providers=')
    expect(parseHash('#providers=')).toEqual({ providers: [] })
    expect(parseHash('#')).toEqual({})
  })

  it('escapes odd characters and round-trips them', () => {
    const s = { models: ['a,b', 'c&d=e'] }
    expect(parseHash(serializeHash(s))).toEqual(s)
  })

  it('ignores junk: unknown keys, pieces without a value, bad escapes, empty list items', () => {
    expect(parseHash('#foo=1&&bar&puzzle=&metric=%E0%A4%A&providers=a,,b&models=ok')).toEqual({ models: ['ok'] })
    expect(parseHash('')).toEqual({})
  })
})
