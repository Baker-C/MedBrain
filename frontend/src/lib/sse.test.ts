import { describe, expect, it } from 'vitest'

import { splitFrames } from './sse'

describe('splitFrames', () => {
  it('reads an event name and its JSON payload', () => {
    const { frames, rest } = splitFrames('event: token\ndata: {"text":"hi"}\n\n')
    expect(frames).toEqual([{ event: 'token', data: '{"text":"hi"}' }])
    expect(rest).toBe('')
  })

  it('returns every complete frame in one buffer', () => {
    const buffer = 'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n'
    expect(splitFrames(buffer).frames).toHaveLength(2)
  })

  it('holds an incomplete trailing frame back as rest', () => {
    const { frames, rest } = splitFrames('event: token\ndata: {"text":"a"}\n\nevent: to')
    expect(frames).toHaveLength(1)
    expect(rest).toBe('event: to')
  })

  it('completes a frame that arrived split across two chunks', () => {
    const first = splitFrames('event: tok')
    expect(first.frames).toEqual([])

    const second = splitFrames(first.rest + 'en\ndata: {"text":"hi"}\n\n')
    expect(second.frames).toEqual([{ event: 'token', data: '{"text":"hi"}' }])
  })

  it('joins multi-line data with newlines, per the SSE spec', () => {
    const { frames } = splitFrames('event: token\ndata: one\ndata: two\n\n')
    expect(frames[0].data).toBe('one\ntwo')
  })

  it('ignores frames carrying no data, such as keep-alive comments', () => {
    expect(splitFrames(': keep-alive\n\n').frames).toEqual([])
  })
})
