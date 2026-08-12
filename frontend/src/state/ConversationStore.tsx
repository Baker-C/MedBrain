/** Owns conversation state: the cache of loaded conversations and the in-flight streams.
 *
 *  Streams live here rather than in a component because a message is persisted server-side
 *  only at `done`. If a streaming answer lived in `ChatArea`, switching conversations
 *  mid-answer would unmount it and destroy text that exists nowhere else.
 *
 *  The cache is deliberately simple: an id→detail map, no TTL and no eviction. It exists
 *  so revisiting a conversation does not refetch, and so a stream can keep writing into a
 *  conversation nobody is currently looking at.
 */

import { useEffect, useReducer, useRef, type ReactNode } from 'react'

import { createConversation, getConversation, listConversations } from '../api/client'
import { streamQuery } from '../api/stream'
import type { Message, Role, SourcesMap } from '../api/types'
import { messageOf } from '../lib/errors'
import { deriveTitle } from '../lib/title'
import {
  ConversationsContext,
  type Answer,
  type ConversationsState,
  type ConversationsValue,
} from './conversations'

type Action =
  | { type: 'conversations/loading' }
  | { type: 'conversations/loaded'; conversations: ConversationsState['conversations'] }
  | { type: 'conversations/failed'; error: string }
  | { type: 'conversation/selected'; id: string | null }
  | { type: 'conversation/created'; conversation: ConversationsState['conversations'][number] }
  | { type: 'detail/loading' }
  | { type: 'detail/loaded'; detail: ConversationsState['details'][string] }
  | { type: 'detail/failed'; error: string }
  | { type: 'message/appended'; conversationId: string; message: Message }
  | { type: 'answer/started'; conversationId: string }
  | { type: 'answer/sources'; conversationId: string; sources: SourcesMap }
  | { type: 'answer/token'; conversationId: string; text: string }
  | { type: 'answer/completed'; conversationId: string; message: Message }
  | { type: 'answer/failed'; conversationId: string; error: string }
  | { type: 'send/failed'; error: string }

const initialState: ConversationsState = {
  conversations: [],
  conversationsLoading: false,
  conversationsError: null,
  activeId: null,
  details: {},
  detailLoading: false,
  detailError: null,
  answers: {},
  sendError: null,
}

function replaceAnswer(
  state: ConversationsState,
  conversationId: string,
  update: (answer: Answer) => Answer,
): ConversationsState {
  const current = state.answers[conversationId]
  if (current === undefined) return state
  return { ...state, answers: { ...state.answers, [conversationId]: update(current) } }
}

function appendMessage(
  state: ConversationsState,
  conversationId: string,
  message: Message,
): ConversationsState {
  const detail = state.details[conversationId]
  if (detail === undefined) return state
  const updated = { ...detail, messages: [...detail.messages, message] }
  return { ...state, details: { ...state.details, [conversationId]: updated } }
}

function dropAnswer(state: ConversationsState, conversationId: string): ConversationsState {
  const answers = { ...state.answers }
  delete answers[conversationId]
  return { ...state, answers }
}

function reducer(state: ConversationsState, action: Action): ConversationsState {
  switch (action.type) {
    case 'conversations/loading':
      return { ...state, conversationsLoading: true, conversationsError: null }
    case 'conversations/loaded':
      return { ...state, conversationsLoading: false, conversations: action.conversations }
    case 'conversations/failed':
      return { ...state, conversationsLoading: false, conversationsError: action.error }

    case 'conversation/selected':
      return { ...state, activeId: action.id, detailError: null, sendError: null }

    case 'conversation/created':
      return {
        ...state,
        activeId: action.conversation.id,
        conversations: [action.conversation, ...state.conversations],
        details: {
          ...state.details,
          [action.conversation.id]: { ...action.conversation, messages: [] },
        },
      }

    case 'detail/loading':
      return { ...state, detailLoading: true, detailError: null }
    case 'detail/loaded':
      return {
        ...state,
        detailLoading: false,
        details: { ...state.details, [action.detail.id]: action.detail },
      }
    case 'detail/failed':
      return { ...state, detailLoading: false, detailError: action.error }

    case 'message/appended':
      return appendMessage(state, action.conversationId, action.message)

    case 'answer/started':
      return {
        ...state,
        sendError: null,
        answers: {
          ...state.answers,
          [action.conversationId]: { text: '', sources: {}, status: 'streaming', error: null },
        },
      }
    case 'answer/sources':
      return replaceAnswer(state, action.conversationId, (a) => ({ ...a, sources: action.sources }))
    case 'answer/token':
      return replaceAnswer(state, action.conversationId, (a) => ({ ...a, text: a.text + action.text }))
    case 'answer/completed':
      return appendMessage(
        dropAnswer(state, action.conversationId),
        action.conversationId,
        action.message,
      )
    case 'answer/failed':
      return replaceAnswer(state, action.conversationId, (a) => ({
        ...a,
        status: 'incomplete',
        error: action.error,
      }))

    case 'send/failed':
      return { ...state, sendError: action.error }
  }
}

/** Client-only ids for optimistic messages. The server issues its own; these never leave
 *  the browser and only need to be unique within a session. */
let localIdCounter = 0

function localMessage(
  conversationId: string,
  role: Role,
  content: string,
  sources: SourcesMap | null,
): Message {
  localIdCounter += 1
  return {
    id: `local-${localIdCounter}`,
    conversation_id: conversationId,
    role,
    content,
    sources,
    created_at: new Date().toISOString(),
  }
}

export function ConversationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const controllers = useRef(new Map<string, AbortController>())

  // Streams outlive the components that started them, so only teardown cancels them.
  useEffect(() => {
    const running = controllers.current
    return () => {
      for (const controller of running.values()) controller.abort()
      running.clear()
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    dispatch({ type: 'conversations/loading' })
    listConversations()
      .then((conversations) => {
        if (!cancelled) dispatch({ type: 'conversations/loaded', conversations })
      })
      .catch((error: unknown) => {
        if (!cancelled) dispatch({ type: 'conversations/failed', error: messageOf(error) })
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function runStream(conversationId: string, question: string) {
    const controller = new AbortController()
    controllers.current.set(conversationId, controller)
    dispatch({ type: 'answer/started', conversationId })

    let text = ''
    let sources: SourcesMap = {}
    try {
      for await (const event of streamQuery(conversationId, { question }, controller.signal)) {
        switch (event.name) {
          case 'sources':
            sources = event.sources
            dispatch({ type: 'answer/sources', conversationId, sources })
            break
          case 'token':
            text += event.text
            dispatch({ type: 'answer/token', conversationId, text: event.text })
            break
          case 'done':
            dispatch({
              type: 'answer/completed',
              conversationId,
              message: localMessage(conversationId, 'assistant', text, sources),
            })
            break
          case 'error':
            dispatch({ type: 'answer/failed', conversationId, error: event.message })
            break
        }
      }
    } catch (error) {
      dispatch({ type: 'answer/failed', conversationId, error: messageOf(error) })
    } finally {
      controllers.current.delete(conversationId)
    }
  }

  async function ask(question: string) {
    let conversationId = state.activeId
    if (conversationId === null) {
      try {
        const conversation = await createConversation(deriveTitle(question))
        dispatch({ type: 'conversation/created', conversation })
        conversationId = conversation.id
      } catch (error) {
        dispatch({ type: 'send/failed', error: messageOf(error) })
        return
      }
    }
    // A partial answer left by a failed stream would be overwritten by the next
    // `answer/started`; keep what arrived by committing it to the transcript first.
    const stalled = state.answers[conversationId]
    if (stalled !== undefined && stalled.status === 'incomplete' && stalled.text !== '') {
      dispatch({
        type: 'answer/completed',
        conversationId,
        message: localMessage(conversationId, 'assistant', stalled.text, stalled.sources),
      })
    }
    dispatch({
      type: 'message/appended',
      conversationId,
      message: localMessage(conversationId, 'user', question, null),
    })
    await runStream(conversationId, question)
  }

  async function select(id: string) {
    dispatch({ type: 'conversation/selected', id })
    if (state.details[id] !== undefined) return
    dispatch({ type: 'detail/loading' })
    try {
      dispatch({ type: 'detail/loaded', detail: await getConversation(id) })
    } catch (error) {
      dispatch({ type: 'detail/failed', error: messageOf(error) })
    }
  }

  function startDraft() {
    dispatch({ type: 'conversation/selected', id: null })
  }

  const activeAnswer = state.activeId === null ? undefined : state.answers[state.activeId]
  const value: ConversationsValue = {
    ...state,
    ask,
    select,
    startDraft,
    streaming: activeAnswer?.status === 'streaming',
  }

  return <ConversationsContext.Provider value={value}>{children}</ConversationsContext.Provider>
}
