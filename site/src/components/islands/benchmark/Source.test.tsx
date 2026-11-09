import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Source } from './Source'

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
})
