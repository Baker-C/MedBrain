import { useState, type FormEvent } from 'react'

import { useConversations } from '../state/conversations'
import { MessageList } from './MessageList'

/** The question box. Disabled while the active conversation is mid-answer, which keeps
 *  one stream per conversation true by construction rather than by reconciliation. */
function Composer({ disabled, onAsk }: { disabled: boolean; onAsk: (question: string) => void }) {
  const [value, setValue] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    const question = value.trim()
    if (question === '' || disabled) return
    setValue('')
    onAsk(question)
  }

  return (
    <form onSubmit={submit} className="w-full max-w-2xl">
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        disabled={disabled}
        aria-label="Ask about the drug labeling"
        placeholder={disabled ? 'Answering…' : 'Ask about the drug labeling'}
        className="w-full rounded-full border border-gray-300 bg-gray-100 px-5 py-3.5 text-gray-800 placeholder-gray-500 focus:ring-2 focus:ring-amber-300 focus:outline-none disabled:opacity-60"
      />
    </form>
  )
}

function EmptyState({ loading }: { loading: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-4">
      <h1 className="text-3xl font-semibold text-gray-800">What do you want to look up?</h1>
      {loading && <p className="text-sm text-gray-500">Loading conversation…</p>}
    </div>
  )
}

export function ChatArea() {
  const { activeId, details, answers, detailLoading, detailError, sendError, ask, streaming } =
    useConversations()

  const detail = activeId === null ? undefined : details[activeId]
  const answer = activeId === null ? undefined : answers[activeId]
  const started = detail !== undefined && (detail.messages.length > 0 || answer !== undefined)
  const error = sendError ?? detailError

  return (
    <div className="flex h-full flex-col">
      <div className="px-4 py-3">
        <span className="text-lg font-semibold text-gray-800">MedBrain</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {started && detail !== undefined ? (
          <MessageList detail={detail} answer={answer} />
        ) : (
          <EmptyState loading={detailLoading} />
        )}
      </div>

      <div className="flex flex-col items-center gap-2 px-4 pb-3">
        {error !== null && (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
        <Composer disabled={streaming} onAsk={(question) => void ask(question)} />
        <p className="text-center text-xs text-gray-500">
          MedBrain answers from FDA drug labeling and cites its sources. It does not give medical
          advice.
        </p>
      </div>
    </div>
  )
}
