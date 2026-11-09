// Spec: docs/specs/site.md. Ported from vladflaks.com's scripts/og-cards.tsx (its benchmarkCard and page frame).
// Renders public/og.png (1200x630), the share image SEO.astro points at, from .data/site.json with the site's
// colour tokens and fonts. Run: `npm run og:card` after the export. The card is generated and never committed.
// Set OG_CHROME to the path of a Chrome binary to use it in place of Playwright's own Chromium.
import { mkdirSync, readFileSync, renameSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { chromium } from '@playwright/test'
import { OneCube } from '../src/components/islands/benchmark/OneCube'
import { ALL } from '../src/lib/benchmark'
import { loadSiteData } from '../src/lib/site-data'

const ROOT = join(import.meta.dirname, '..')
const OUT = join(ROOT, 'public', 'og.png')
const SCRATCH = join(ROOT, 'tmp', `og-card-${process.pid}.png`)
const TOP = 6

// The site's colour tokens (global.css :root, dark) and the cube drawing's rules (cube-stage.css).
const tokens = readFileSync(join(ROOT, 'src/styles/global.css'), 'utf8').match(/:root\s*{[^}]*}/)![0]
const cubeCss = readFileSync(join(ROOT, 'src/styles/cube-stage.css'), 'utf8')

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

const { page, metrics } = loadSiteData()
const rows = metrics
  .filter((m) => m.puzzle === ALL && m.precision.value !== null)
  .map((m) => ({ model: m.model, value: m.precision.value as number }))
  .sort((a, b) => b.value - a.value || (a.model < b.model ? -1 : a.model > b.model ? 1 : 0))
  .slice(0, TOP)
if (rows.length === 0) throw new Error('og:card: no "all" metrics rows with a balanced precision to chart')

const chart = rows.map((r, i) => {
  const pct = Math.round(r.value * 100)
  return `<div class="row"><div class="label"><span>${esc(r.model)}</span><span class="pct">${pct}%</span></div>
    <div class="track"><div class="fill" style="width:${pct}%;background:${i === 0 ? 'var(--ok)' : 'var(--link)'}"></div></div></div>`
}).join('')

const html = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;500&family=Space+Mono:wght@400;700&display=block">
<style>${tokens.replace(/--font-body:[^;]*;|--font-mono:[^;]*;/g, '')}
${cubeCss}
html, body { margin: 0; }
#card { width: 1200px; height: 630px; overflow: hidden; background: var(--bg); color: var(--text); font-family: Roboto, sans-serif; }
.bar { height: 14px; background: var(--link); }
.bench { display: grid; grid-template-columns: 450px 1fr; gap: 56px; align-items: center; height: calc(100% - 14px); padding: 0 72px 0 80px; }
.cube { width: 96px; height: 96px; margin-bottom: 22px; }
.cube svg { width: 100%; height: 100%; display: block; }
h1 { font: 500 60px/1.08 Roboto, sans-serif; color: var(--head); margin: 0 0 22px; }
.lede { font: 300 29px/1.35 Roboto, sans-serif; color: var(--text); }
.panel { background: var(--panel); border: 1px solid var(--code-rule); padding: 28px 32px 14px; font: 400 22px/1.15 'Space Mono', monospace; }
.panel .cap { font: 400 17px 'Space Mono', monospace; color: var(--muted); margin-bottom: 20px; }
.row { margin-bottom: 20px; }
.label { display: flex; justify-content: space-between; gap: 16px; }
.pct { color: var(--muted); }
.track { height: 10px; margin-top: 7px; background: var(--rule); }
.fill { height: 100%; }
</style></head><body><div id="card"><div class="bar"></div>
<div class="bench">
  <div><div class="cube cube-solver"><div class="cube-stage">${renderToStaticMarkup(createElement(OneCube))}</div></div>
    <h1>${esc(page.title)}</h1><div class="lede">${esc(page.description)}</div></div>
  <div class="panel"><div class="cap">Balanced precision, all puzzles</div>${chart}</div>
</div></div></body></html>`

mkdirSync(join(ROOT, 'tmp'), { recursive: true })
const executablePath = process.env.OG_CHROME || undefined
const browser = await chromium.launch(executablePath ? { executablePath } : {})
try {
  const p = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 })
  await p.setContent(html, { waitUntil: 'networkidle' })
  // A card drawn in a fallback font is wrong: fail instead of publishing it.
  const ok = await p.evaluate(async () => {
    await Promise.all([document.fonts.load('500 60px Roboto'), document.fonts.load('300 29px Roboto'), document.fonts.load('400 22px "Space Mono"')]).catch(() => {})
    await document.fonts.ready
    const families = new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, '')))
    return families.has('Roboto') && families.has('Space Mono') && document.fonts.check('500 60px Roboto') && document.fonts.check('400 22px "Space Mono"')
  })
  if (!ok) throw new Error('og:card: fonts did not load')
  await p.locator('#card').screenshot({ path: SCRATCH, type: 'png' })
  renameSync(SCRATCH, OUT)
  console.log('og:card', OUT)
} catch (e) {
  rmSync(SCRATCH, { force: true })
  throw e
} finally {
  await browser.close()
}
