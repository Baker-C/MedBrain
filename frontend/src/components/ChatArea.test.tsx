/** The wired path, end to end against a stubbed fetch: ask a question, stream tokens into
 *  the DOM, resolve a citation to a signed URL, and survive a stream that dies halfway. */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import type { Citation, Conversation } from '../api/types'
import { frame, jsonResponse, streamResponse } from '../test/sse'

const CITATION: Citation = {
  document_id: 'warfarin',
  drug: 'warfarin',
  section_number: '5.1',
  section_title: 'Hemorrhage',
  page_start: 7,
}

const CONVERSATION: Conversation = {
  id: 'c1',
  title: 'What is the INR target?',
  created_at: '2026-08-12T00:00:00Z',
}

const SIGNED_URL = 'https://storage.example/warfarin.pdf?token=abc'

/** Routes the four requests this flow makes; anything else is a test bug, not a fallback. */
function stubBackend(streamChunks: string[]) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (url.endsWith('/conversations') && method === 'GET') return Promise.resolve(jsonResponse([]))
    if (url.endsWith('/conversations') && method === 'POST')
      return Promise.resolve(jsonResponse(CONVERSATION))
    if (url.endsWith('/query')) return Promise.resolve(streamResponse(streamChunks))
    if (url.endsWith('/source-url')) return Promise.resolve(jsonResponse({ url: SIGNED_URL }))

    return Promise.reject(new Error(`unexpected request: ${method} ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function ask(question: string) {
  const input = await screen.findByRole('textbox', { name: /ask about the drug labeling/i })
  fireEvent.change(input, { target: { value: question } })
  fireEvent.submit(input)
  return input
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('asking a question', () => {
  it('creates the conversation, streams the answer, and resolves its citation', async () => {
    const fetchMock = stubBackend([
      frame('sources', { sources: { S1: CITATION } }),
      frame('token', { text: 'Monitor INR at baseline ' }),
      frame('token', { text: '[[S1]] and then weekly.' }),
      frame('done', { judge_grounded: null }),
    ])
    const open = vi.spyOn(window, 'open').mockReturnValue(null)

    render(<App />)
    await ask('What is the INR target?')

    // The question appears immediately, before any answer arrives. Scoped to the
    // transcript because the sidebar shows the same text as the conversation title.
    const messages = await screen.findByRole('list', { name: 'Messages' })
    expect(within(messages).getByText('What is the INR target?')).toBeInTheDocument()

    // Tokens accumulate into the answer, and the sentinel becomes a real citation.
    expect(await screen.findByText(/Monitor INR at baseline/)).toBeInTheDocument()
    const citation = await screen.findByRole('button', { name: /warfarin § 5.1 Hemorrhage/i })

    // The conversation was created lazily, on send, and titled from the question.
    const createCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === 'POST' && String(init.body).includes('title'),
    )
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      title: 'What is the INR target?',
    })

    // Clicking mints a signed URL and deep-links to the cited page.
    fireEvent.click(citation)
    await waitFor(() => {
      expect(open).toHaveBeenCalledWith(
        `${SIGNED_URL}#page=7`,
        '_blank',
        'noopener,noreferrer',
      )
    })
  })

  it('keeps the partial answer and labels it when the stream dies mid-flight', async () => {
    stubBackend([
      frame('sources', { sources: { S1: CITATION } }),
      frame('token', { text: 'Monitor INR at baseline' }),
      // No done, no error: the connection simply drops.
    ])

    render(<App />)
    await ask('What is the INR target?')

    expect(await screen.findByText(/Monitor INR at baseline/)).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(/connection was lost/i)
  })

  it('re-enables the composer once the answer completes', async () => {
    stubBackend([
      frame('token', { text: 'Answer.' }),
      frame('done', { judge_grounded: null }),
    ])

    render(<App />)
    const input = await ask('What is the INR target?')

    await screen.findByText('Answer.')
    await waitFor(() => {
      expect(input).not.toBeDisabled()
    })
  })
})
