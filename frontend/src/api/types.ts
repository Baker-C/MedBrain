// Types mirroring the backend API surface described in DESIGN.md.
// Types and endpoint paths only — no fetch logic yet.

export type Role = 'user' | 'assistant'

/** One resolved citation. Precision degrades gracefully: section fields and page are nullable. */
export interface Citation {
  document_id: string
  drug: string
  section_number: string | null
  section_title: string | null
  page_start: number | null
}

/** Sentinel tag (e.g. "S1") → citation mapping, sent as the first SSE event. */
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

/** POST /conversations request body. */
export interface CreateConversationRequest {
  title?: string
}

export type RetrievalMode = 'hybrid' | 'dense' | 'sparse'

/**
 * POST /conversations/{id}/query request body.
 * Pipeline config is an explicit input per request, never ambient state.
 */
export interface QueryRequest {
  question: string
  mode?: RetrievalMode
  rewrite?: boolean
  rerank?: boolean
  gating_variant?: string
  judge?: boolean
}

/** SSE event names on the query stream, in emission order. */
export type QueryEventName = 'sources' | 'token' | 'done' | 'error'

/** `done` event payload — post-hoc annotations (e.g. the live judge's grounding flag). */
export interface DonePayload {
  judge_grounded?: boolean
}

/** `error` event payload. */
export interface ErrorPayload {
  message: string
}

/** GET /documents/{id}/source-url — short-lived signed URL for the source PDF. */
export interface SourceUrlResponse {
  url: string
}

/** GET /health */
export interface HealthResponse {
  status: string
}
