/** The query stream adapter.
 *
 *  `EventSource` only issues GET requests, and the query endpoint is a POST, so the
 *  response body is read and framed by hand.
 */

import { ENDPOINTS } from './endpoints'
import { ApiError, apiUrl, errorMessage, JSON_HEADERS } from './http'
import { splitFrames, type SseFrame } from '../lib/sse'
import type { QueryEvent, QueryRequest, SourcesMap } from './types'

/** The stream ended without `done` or `error`: the connection dropped mid-answer.
 *
 *  A dropped connection is indistinguishable from a clean finish at the byte level —
 *  the reader simply ends — so the only evidence is the absence of a terminal event. */
export class StreamInterruptedError extends Error {
  constructor() {
    super('The connection was lost before the answer finished.')
    this.name = 'StreamInterruptedError'
  }
}

const TERMINAL_EVENTS: ReadonlySet<string> = new Set(['done', 'error'])

/** One frame as a typed event. Null for anything the contract does not define. */
function toEvent(frame: SseFrame): QueryEvent | null {
  const payload = JSON.parse(frame.data) as Record<string, unknown>
  switch (frame.event) {
    case 'sources':
      return { name: 'sources', sources: payload.sources as SourcesMap }
    case 'token':
      return { name: 'token', text: payload.text as string }
    case 'done':
      return { name: 'done', judge_grounded: (payload.judge_grounded ?? null) as boolean | null }
    case 'error':
      return { name: 'error', message: payload.message as string }
    default:
      return null
  }
}

/** Each SSE event as it arrives. Throws `StreamInterruptedError` if the body ends
 *  before a terminal event. */
export async function* streamQuery(
  conversationId: string,
  body: QueryRequest,
  signal: AbortSignal,
): AsyncGenerator<QueryEvent> {
  const response = await fetch(apiUrl(ENDPOINTS.query(conversationId)), {
    method: 'POST',
    headers: { ...JSON_HEADERS, Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  if (response.body === null) throw new StreamInterruptedError()

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawTerminal = false

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const { frames, rest } = splitFrames(buffer)
      buffer = rest
      for (const frame of frames) {
        const event = toEvent(frame)
        if (event === null) continue
        if (TERMINAL_EVENTS.has(event.name)) sawTerminal = true
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }

  if (!sawTerminal) throw new StreamInterruptedError()
}
