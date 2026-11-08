// Reads site/.data/site.json, which `python -m src.site.export` writes (see docs/specs/site-export.md).
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { BenchmarkExperiment } from './types'

export interface SiteData {
  page: { title: string; description: string; intro: string }
  definitions: { key: string; name: string; definition: string }[]
  experiments: BenchmarkExperiment[]
}

// Astro bundles this module into dist/, so a path relative to the source file would break; the build runs from site/.
const FILE = resolve(process.cwd(), '.data/site.json')

export function loadSiteData(): SiteData {
  if (!existsSync(FILE)) {
    throw new Error('site/.data/site.json is missing. Run `python -m src.site.export --out site/.data/site.json` from the repo root first.')
  }
  return JSON.parse(readFileSync(FILE, 'utf8')) as SiteData
}
