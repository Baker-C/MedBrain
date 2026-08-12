/** The non-streaming endpoints. The query stream lives in `stream.ts`. */

import { ENDPOINTS } from './endpoints'
import { JSON_HEADERS, request } from './http'
import type {
  Conversation,
  ConversationDetail,
  CreateConversationRequest,
  SourceUrlResponse,
} from './types'

export function createConversation(title: string): Promise<Conversation> {
  const body: CreateConversationRequest = { title }
  return request(ENDPOINTS.conversations, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  })
}

export function listConversations(): Promise<Conversation[]> {
  return request(ENDPOINTS.conversations)
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request(ENDPOINTS.conversation(id))
}

export function getSourceUrl(documentId: string): Promise<SourceUrlResponse> {
  return request(ENDPOINTS.documentSourceUrl(documentId))
}

/** The signed URL with its cited page appended. The fragment stays client-side, so it
 *  cannot break the signature. */
export function withPage(url: string, page: number): string {
  return `${url}#page=${page}`
}
