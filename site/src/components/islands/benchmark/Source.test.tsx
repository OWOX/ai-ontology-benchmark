import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Source, formatTokens, usage } from './Source'

afterEach(cleanup)

describe('Source', () => {
  it('names the repository with a link and says where the numbers come from', () => {
    const { container } = render(<Source />)
    const section = screen.getByRole('region', { name: 'Source' })
    expect(section.querySelector('.num svg')).not.toBeNull()
    const link = screen.getByRole('link', { name: /^github\.com\/OWOX\/ai-ontology-benchmark/ })
    expect(link).toHaveAttribute('href', 'https://github.com/OWOX/ai-ontology-benchmark')
    expect(link).toHaveTextContent(/^github\.com\/OWOX\/ai-ontology-benchmark/)
    expect(container).toHaveTextContent(/Every number on this page is recomputed from those raw answers\./)
  })

  it('leads the note with the attempts and tokens shown, and says nothing of them without', () => {
    const { container, rerender } = render(<Source shown={{ attempts: 12345, tokens: 67_800_000 }} />)
    expect(container).toHaveTextContent(/12,345 attempts and 67\.8 million tokens\. The repository holds/)
    rerender(<Source />)
    expect(container).not.toHaveTextContent(/attempts and/)
  })

  it('formats tokens as millions with one decimal, thousands with k, or as they are', () => {
    expect(formatTokens(67_849_999)).toBe('67.8 million')
    expect(formatTokens(1_000_000)).toBe('1.0 million')
    expect(formatTokens(999_499)).toBe('999k')
    expect(formatTokens(999_500)).toBe('1.0 million')
    expect(formatTokens(999_999)).toBe('1.0 million')
    expect(formatTokens(12_345)).toBe('12k')
    expect(formatTokens(999)).toBe('999')
    expect(usage(1, 1)).toBe('1 attempt and 1 token.')
  })
})
