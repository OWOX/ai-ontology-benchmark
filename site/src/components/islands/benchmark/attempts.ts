import type { ReplayAttempt } from './Player'

/** The body of attempts.json: the attempts by puzzle, and the prompts they point at (each attempt's `prompt` is a key of `prompts`). */
export interface AttemptsData {
  attempts: Record<string, ReplayAttempt[]>
  prompts: Record<string, string>
}

const loads = new Map<string, Promise<AttemptsData>>()

/** attempts.json is fetched once per page load, whichever Player asks; a failed load is dropped so the next Run retries. */
export function loadAttempts(url: string): Promise<AttemptsData> {
  let load = loads.get(url)
  if (!load) {
    load = fetch(url).then((res) => {
      if (!res.ok) throw new Error(String(res.status))
      return res.json() as Promise<AttemptsData>
    })
    loads.set(url, load)
    load.catch(() => loads.delete(url))
  }
  return load
}

/** For tests: forget what was loaded. */
export const resetAttempts = () => loads.clear()
