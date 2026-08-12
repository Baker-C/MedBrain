import { useEffect, useRef } from 'react'

import type { ConversationDetail, Message } from '../api/types'
import type { Answer } from '../state/conversations'
import { AnswerText } from './AnswerText'

function UserMessage({ content }: { content: string }) {
  return (
    <li className="flex justify-end">
      <p className="max-w-2xl rounded-2xl bg-gray-100 px-4 py-2.5 whitespace-pre-wrap text-gray-800">
        {content}
      </p>
    </li>
  )
}

function AssistantMessage({ message }: { message: Message }) {
  return (
    <li className="max-w-3xl leading-relaxed text-gray-800">
      <AnswerText text={message.content} sources={message.sources ?? {}} streaming={false} />
    </li>
  )
}

/** The answer currently streaming, or the partial one left behind when a stream stopped.
 *
 *  Partial text is kept and labeled rather than discarded — the answer got as far as it
 *  got, and hiding that is less honest than showing it. */
function StreamingAnswer({ answer }: { answer: Answer }) {
  const waiting = answer.status === 'streaming' && answer.text === ''
  return (
    <li className="max-w-3xl leading-relaxed text-gray-800">
      {waiting ? (
        <span className="animate-pulse text-gray-500">Searching the labeling…</span>
      ) : (
        <AnswerText
          text={answer.text}
          sources={answer.sources}
          streaming={answer.status === 'streaming'}
        />
      )}
      {answer.status === 'incomplete' && (
        <p role="alert" className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {answer.error ?? 'This answer is incomplete.'}
        </p>
      )}
    </li>
  )
}

export function MessageList({
  detail,
  answer,
}: {
  detail: ConversationDetail
  answer: Answer | undefined
}) {
  // Keeps the newest text in view as messages land and tokens stream in.
  // The optional call also covers jsdom, which has no scrollIntoView.
  const endRef = useRef<HTMLLIElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView?.()
  }, [detail.messages.length, answer?.text])

  return (
    <ul aria-label="Messages" className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      {detail.messages.map((message) =>
        message.role === 'user' ? (
          <UserMessage key={message.id} content={message.content} />
        ) : (
          <AssistantMessage key={message.id} message={message} />
        ),
      )}
      {answer !== undefined && <StreamingAnswer answer={answer} />}
      <li ref={endRef} aria-hidden="true" />
    </ul>
  )
}
