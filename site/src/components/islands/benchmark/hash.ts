/** The filter state kept in `location.hash`. Each key is optional: an absent key means its default. */
export interface HashState {
  puzzle?: string
  /** Ticked provider ids; `[]` means none ticked (`providers=`). */
  providers?: string[]
  /** Selected model names; `[]` means none selected (`models=`). */
  models?: string[]
  metric?: string
}

const LISTS = ['providers', 'models'] as const

const decode = (s: string) => {
  try { return decodeURIComponent(s) } catch { return null }
}

/** `#puzzle=3x3&providers=a,b&models=m1,m2&metric=hallucination` -> the keys it holds. Unknown keys, empty puzzle/metric and undecodable pieces are dropped; the caller checks values against what exists. */
export function parseHash(hash: string): HashState {
  const out: HashState = {}
  for (const pair of hash.replace(/^#/, '').split('&')) {
    const eq = pair.indexOf('=')
    if (eq === -1) continue
    const key = decode(pair.slice(0, eq))
    const raw = pair.slice(eq + 1)
    if (key === 'puzzle' || key === 'metric') {
      const v = decode(raw)
      if (v) out[key] = v
    } else if ((LISTS as readonly (string | null)[]).includes(key)) {
      const items = raw === '' ? [] : raw.split(',').map(decode)
      if (items.every((v): v is string => v !== null && v !== '')) out[key as (typeof LISTS)[number]] = items
    }
  }
  return out
}

/** The inverse of parseHash; '' when every key is absent, so the default page carries no hash. */
export function serializeHash(s: HashState): string {
  const parts: string[] = []
  if (s.puzzle !== undefined) parts.push(`puzzle=${encodeURIComponent(s.puzzle)}`)
  if (s.providers !== undefined) parts.push(`providers=${s.providers.map(encodeURIComponent).join(',')}`)
  if (s.models !== undefined) parts.push(`models=${s.models.map(encodeURIComponent).join(',')}`)
  if (s.metric !== undefined) parts.push(`metric=${encodeURIComponent(s.metric)}`)
  return parts.length ? `#${parts.join('&')}` : ''
}
