import type { ReplayAttempt } from './Player'

const loads = new Map<string, Promise<Record<string, ReplayAttempt[]>>>()

/** attempts.json is fetched once per page load, whichever Player asks; a failed load is dropped so the next Run retries. */
export function loadAttempts(url: string): Promise<Record<string, ReplayAttempt[]>> {
  let load = loads.get(url)
  if (!load) {
    load = fetch(url).then((res) => {
      if (!res.ok) throw new Error(String(res.status))
      return res.json() as Promise<Record<string, ReplayAttempt[]>>
    })
    loads.set(url, load)
    load.catch(() => loads.delete(url))
  }
  return load
}

/** For tests: forget what was loaded. */
export const resetAttempts = () => loads.clear()
