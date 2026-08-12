import { describe, expect, it } from 'vitest'

import { answerSegments, splitHeldSuffix, toSegments } from './sentinels'

describe('toSegments', () => {
  it('separates prose from citation tags', () => {
    expect(toSegments('Monitor INR [[S1]] closely.')).toEqual([
      { kind: 'text', text: 'Monitor INR ' },
      { kind: 'citation', tag: 'S1' },
      { kind: 'text', text: ' closely.' },
    ])
  })

  it('handles several tags, including adjacent ones', () => {
    expect(toSegments('[[S1]][[S12]]')).toEqual([
      { kind: 'citation', tag: 'S1' },
      { kind: 'citation', tag: 'S12' },
    ])
  })

  it('leaves text with no tags untouched', () => {
    expect(toSegments('plain')).toEqual([{ kind: 'text', text: 'plain' }])
  })
})

describe('splitHeldSuffix', () => {
  it.each(['[', '[[', '[[S', '[[S1', '[[S12', '[[S1]'])('withholds the partial tag %j', (partial) => {
    expect(splitHeldSuffix(`done ${partial}`)).toEqual({ ready: 'done ', held: partial })
  })

  it('withholds nothing when the tag is complete', () => {
    expect(splitHeldSuffix('done [[S1]]')).toEqual({ ready: 'done [[S1]]', held: '' })
  })
})

describe('answerSegments', () => {
  it('never renders a half-arrived sentinel as literal text while streaming', () => {
    expect(answerSegments('Monitor INR [[S', true)).toEqual([
      { kind: 'text', text: 'Monitor INR ' },
    ])
  })

  it('resolves the tag once its closing brackets arrive', () => {
    expect(answerSegments('Monitor INR [[S1]]', true)).toEqual([
      { kind: 'text', text: 'Monitor INR ' },
      { kind: 'citation', tag: 'S1' },
    ])
  })

  it('flushes a held fragment once the stream has finished', () => {
    expect(answerSegments('cost [50', false)).toEqual([{ kind: 'text', text: 'cost [50' }])
  })
})
