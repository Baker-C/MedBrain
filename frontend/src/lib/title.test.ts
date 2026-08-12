import { describe, expect, it } from 'vitest'

import { deriveTitle } from './title'

describe('deriveTitle', () => {
  it('collapses surrounding and repeated whitespace', () => {
    expect(deriveTitle('  What is the\n\n  INR target?  ')).toBe('What is the INR target?')
  })

  it('truncates a long question to a title-sized string', () => {
    const title = deriveTitle('w'.repeat(200))
    expect(title).toHaveLength(60)
    expect(title.endsWith('…')).toBe(true)
  })
})
