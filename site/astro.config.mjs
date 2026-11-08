// astro.config.mjs
import { defineConfig, fontProviders } from 'astro/config'
import react from '@astrojs/react'

export default defineConfig({
  site: 'https://owox.github.io',
  base: '/ai-ontology-benchmark',
  output: 'static',
  // Self-hosted via Astro's Fonts API, as on vladflaks.com.
  fonts: [
    {
      provider: fontProviders.google(),
      name: 'Figtree',
      cssVariable: '--font-figtree',
      weights: [300, 700, 800],
      subsets: ['latin'],
      display: 'fallback',
    },
    {
      provider: fontProviders.google(),
      name: 'Newsreader',
      cssVariable: '--font-newsreader',
      weights: [400, 700],
      subsets: ['latin', 'cyrillic'],
      fallbacks: ['Georgia', 'serif'],
      display: 'fallback',
    },
  ],
  integrations: [react()],
  build: { inlineStylesheets: 'always' },
})
