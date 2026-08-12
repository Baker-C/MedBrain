/** Builders for the SSE wire format the backend emits, used to drive a stubbed fetch. */

/** One frame, encoded exactly as `encode_sse` in backend/chat/events.py does. */
export function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

/** A response body that emits the given strings as separate network chunks.
 *
 *  Chunk boundaries are the point: passing a frame split across two entries is how the
 *  parser's buffering gets exercised. */
export function bodyOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

export function streamResponse(chunks: string[]): Response {
  return new Response(bodyOf(chunks), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

export function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
