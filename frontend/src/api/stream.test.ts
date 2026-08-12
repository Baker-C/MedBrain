import { afterEach, describe, expect, it, vi } from 'vitest'

import { frame, streamResponse } from '../test/sse'
import { ApiError } from './http'
import { StreamInterruptedError, streamQuery } from './stream'
import type { Citation, QueryEvent } from './types'

const CITATION: Citation = {
  document_id: 'warfarin',
  drug: 'warfarin',
  section_number: '5.1',
  section_title: 'Hemorrhage',
  page_start: 7,
}

function respondWith(response: Response) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
}

async function collect(chunks: string[]): Promise<QueryEvent[]> {
  respondWith(streamResponse(chunks))
  const events: QueryEvent[] = []
  for await (const event of streamQuery('c1', { question: 'q' }, new AbortController().signal)) {
    events.push(event)
  }
  return events
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('streamQuery', () => {
  it('yields the events in contract order and unwraps the sources payload', async () => {
    const events = await collect([
      frame('sources', { sources: { S1: CITATION } }),
      frame('token', { text: 'Monitor INR' }),
      frame('done', { judge_grounded: null }),
    ])

    expect(events).toEqual([
      { name: 'sources', sources: { S1: CITATION } },
      { name: 'token', text: 'Monitor INR' },
      { name: 'done', judge_grounded: null },
    ])
  })

  it('preserves newlines inside token text', async () => {
    const events = await collect([
      frame('token', { text: 'Baseline.\n\n1. Check INR' }),
      frame('done', { judge_grounded: null }),
    ])

    expect(events[0]).toEqual({ name: 'token', text: 'Baseline.\n\n1. Check INR' })
  })

  it('reassembles a frame that arrived split across network chunks', async () => {
    const whole = frame('token', { text: 'hello' })
    const events = await collect([
      whole.slice(0, 12),
      whole.slice(12),
      frame('done', { judge_grounded: null }),
    ])

    expect(events[0]).toEqual({ name: 'token', text: 'hello' })
  })

  it('throws when the body ends without a terminal event', async () => {
    await expect(collect([frame('token', { text: 'partial' })])).rejects.toBeInstanceOf(
      StreamInterruptedError,
    )
  })

  it('treats an explicit error event as a clean termination, not an interruption', async () => {
    const events = await collect([
      frame('token', { text: 'partial' }),
      frame('error', { message: 'Generation failed.' }),
    ])

    expect(events.at(-1)).toEqual({ name: 'error', message: 'Generation failed.' })
  })

  it('raises the backend detail when the request is rejected before streaming', async () => {
    respondWith(
      new Response(JSON.stringify({ detail: 'No such conversation' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const start = streamQuery('missing', { question: 'q' }, new AbortController().signal)
    await expect(start.next()).rejects.toThrow(ApiError)
  })
})
