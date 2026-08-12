// Mirrors the backend contract: `chat/events.py` (SSE payloads), `chat/context.py`
// (Citation), and `persistence/rows.py` (conversations, messages).
//
// These are compile-time shapes only — responses are cast, not validated. A backend
// rename therefore surfaces as a broken render, not a typed error at the boundary.
// Deliberate: see DESIGN_RECORDS.

export type Role = 'user' | 'assistant'

/** One resolved source. Section fields degrade to null on a chunk with no carved
 *  section; `page_start` is the guaranteed floor every citation deep-links to. */
export interface Citation {
  document_id: string
  drug: string
  section_number: string | null
  section_title: string | null
  page_start: number
}

/** Sentinel tag → citation. Keys carry no brackets (`S1`); answer text carries `[[S1]]`. */
export type SourcesMap = Record<string, Citation>

export interface Conversation {
  id: string
  title: string
  created_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: Role
  content: string
  sources: SourcesMap | null
  created_at: string
}

/** GET /conversations/{id} — one conversation with its messages. */
export interface ConversationDetail extends Conversation {
  messages: Message[]
}

/** POST /conversations. Title is set here or never — the API has no PATCH. */
export interface CreateConversationRequest {
  title: string
}

/**
 * POST /conversations/{id}/query body.
 *
 * Pipeline toggles are an explicit per-request input, never ambient state, so the eval
 * harness can vary one at a time. Omitted toggles take the backend default. There is
 * deliberately no retrieval "mode": dense search always runs and everything else is an
 * independent switch. The UI sends none of them.
 */
export interface QueryRequest {
  question: string
  gate?: boolean
  rewrite?: boolean
  sparse?: boolean
  rerank?: boolean
  judge?: boolean
}

/**
 * The four SSE events, normalized into one union keyed by event name.
 *
 * Order is `sources` (before any token, so sentinels always resolve) → `token`s →
 * `done` or `error`. Each frame's payload is JSON, so newlines in answer text cannot
 * break framing.
 */
export type QueryEvent =
  | { name: 'sources'; sources: SourcesMap }
  | { name: 'token'; text: string }
  | { name: 'done'; judge_grounded: boolean | null }
  | { name: 'error'; message: string }

/** GET /documents/{id}/source-url — short-lived signed URL for the source PDF. */
export interface SourceUrlResponse {
  url: string
}

/** GET /health */
export interface HealthResponse {
  status: string
}
