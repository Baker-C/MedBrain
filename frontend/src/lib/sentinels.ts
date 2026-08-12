/** Answer text carries citation sentinels (`[[S1]]`) exactly as the model emitted them;
 *  resolving them is the client's job. Pure logic, no API types.
 *
 *  Tokens arrive in arbitrary pieces, so a sentinel can be split across two of them
 *  (`[[S` then `1]]`). While streaming, a trailing fragment that might still become a
 *  tag is withheld, so it never flashes on screen as literal text.
 */

export type Segment = { kind: 'text'; text: string } | { kind: 'citation'; tag: string }

/** Mirrors TAG_PATTERN in backend/chat/context.py. */
const COMPLETE_TAG = /\[\[(S\d+)\]\]/g
const TRAILING_PARTIAL_TAG = /\[\[?S?\d*\]?$/

/** The text safe to show now, and the suffix that may still turn into a tag. */
export function splitHeldSuffix(text: string): { ready: string; held: string } {
  const match = TRAILING_PARTIAL_TAG.exec(text)
  if (match === null) return { ready: text, held: '' }
  return { ready: text.slice(0, match.index), held: match[0] }
}

/** Text split into prose and the citation tags embedded in it. */
export function toSegments(text: string): Segment[] {
  const segments: Segment[] = []
  let cursor = 0
  for (const match of text.matchAll(COMPLETE_TAG)) {
    const start = match.index ?? 0
    if (start > cursor) segments.push({ kind: 'text', text: text.slice(cursor, start) })
    segments.push({ kind: 'citation', tag: match[1] })
    cursor = start + match[0].length
  }
  if (cursor < text.length) segments.push({ kind: 'text', text: text.slice(cursor) })
  return segments
}

/** Renderable segments. While streaming, a half-arrived sentinel is held back. */
export function answerSegments(text: string, streaming: boolean): Segment[] {
  return toSegments(streaming ? splitHeldSuffix(text).ready : text)
}
