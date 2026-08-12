/** The conversation store's shape and its consumer hook.
 *
 *  Separate from the provider so the provider module exports only a component, which is
 *  what React Fast Refresh requires.
 */

import { createContext, useContext } from 'react'

import type { Conversation, ConversationDetail, SourcesMap } from '../api/types'

/** An answer still streaming, or one that stopped early. A completed answer becomes a
 *  `Message` on the conversation detail and its entry here is dropped. */
export interface Answer {
  text: string
  sources: SourcesMap
  status: 'streaming' | 'incomplete'
  error: string | null
}

export interface ConversationsState {
  conversations: Conversation[]
  conversationsLoading: boolean
  conversationsError: string | null
  /** null means the draft conversation — "New chat" before its first question. */
  activeId: string | null
  details: Record<string, ConversationDetail>
  detailLoading: boolean
  detailError: string | null
  answers: Record<string, Answer>
  sendError: string | null
}

export interface ConversationsValue extends ConversationsState {
  /** Ask in the active conversation, creating it first if this is the draft. */
  ask: (question: string) => Promise<void>
  /** Show a conversation, fetching it only on a cache miss. */
  select: (id: string) => Promise<void>
  /** Return to the empty draft. Creates nothing server-side. */
  startDraft: () => void
  /** Whether the active conversation is mid-answer. */
  streaming: boolean
}

export const ConversationsContext = createContext<ConversationsValue | null>(null)

export function useConversations(): ConversationsValue {
  const value = useContext(ConversationsContext)
  if (value === null) throw new Error('useConversations must be used inside ConversationProvider')
  return value
}
