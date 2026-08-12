/** Incremental SSE frame parsing. Pure: a buffer in, complete frames plus leftover out.
 *
 * A network chunk can end anywhere — mid-frame, mid-line, even mid-UTF-8-character —
 * so the caller keeps `rest` and prepends it to the next chunk.
 */

export interface SseFrame {
  event: string
  data: string
}

const FRAME_BOUNDARY = /\r?\n\r?\n/
const LINE_BOUNDARY = /\r?\n/

/** One frame's event name and its joined `data:` payload. Null when it carries no data. */
function parseFrame(raw: string): SseFrame | null {
  const data: string[] = []
  let event = ''
  for (const line of raw.split(LINE_BOUNDARY)) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      data.push(line.slice('data:'.length).replace(/^ /, ''))
    }
  }
  return data.length > 0 ? { event, data: data.join('\n') } : null
}

/** Every complete frame in the buffer, and the trailing partial frame still to come. */
export function splitFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  const parts = buffer.split(FRAME_BOUNDARY)
  const rest = parts.pop() ?? ''
  const frames = parts
    .map(parseFrame)
    .filter((frame): frame is SseFrame => frame !== null)
  return { frames, rest }
}
