// Spec: docs/specs/site.md
import { defineConfig, fontProviders } from 'astro/config'
import react from '@astrojs/react'

export default defineConfig({
  site: 'https://owox.github.io',
  base: '/ai-ontology-benchmark',
  output: 'static',
  // Self-hosted via Astro's Fonts API. The two fonts of owox.com's astro.config.mjs.
  fonts: [
    {
      name: 'Roboto',
      cssVariable: '--font-roboto',
      provider: fontProviders.google(),
      weights: ['300 500'],
      styles: ['normal', 'italic'],
    },
    {
      name: 'Space Mono',
      cssVariable: '--font-space-mono',
      provider: fontProviders.google(),
      weights: [400, 700],
    },
  ],
  integrations: [react()],
  build: { inlineStylesheets: 'always' },
})
