import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { OneCube } from '../../scripts/OneCube'

const script = join(__dirname, '../../scripts/og-card.tsx')

describe('share card script', () => {
  it('imports only files that exist, so `npm run og:card` cannot break on a removed component', () => {
    const imports = [...readFileSync(script, 'utf8').matchAll(/from '(\.[^']+)'/g)].map((m) => m[1])
    expect(imports.length).toBeGreaterThan(0)
    for (const spec of imports) {
      const base = join(dirname(script), spec)
      expect(['.ts', '.tsx', '/index.ts', '/index.tsx'].some((ext) => existsSync(base + ext)), spec).toBe(true)
    }
  })

  it('draws the 1x1x1 cube with one sticker per visible face', () => {
    const svg = renderToStaticMarkup(createElement(OneCube))
    expect(svg.match(/class="sticker"/g)).toHaveLength(3)
  })
})
