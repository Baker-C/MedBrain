import { useConversations } from '../state/conversations'

export function ConversationList() {
  const { conversations, conversationsLoading, conversationsError, activeId, select } =
    useConversations()

  return (
    <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
      {conversationsLoading && <p className="px-2 text-sm text-gray-500">Loading…</p>}
      {conversationsError !== null && (
        <p role="alert" className="px-2 text-sm text-red-700">
          {conversationsError}
        </p>
      )}
      <ul className="flex flex-col gap-0.5">
        {conversations.map((conversation) => (
          <li key={conversation.id}>
            <button
              type="button"
              onClick={() => void select(conversation.id)}
              aria-current={conversation.id === activeId ? 'true' : undefined}
              className={`w-full truncate rounded-lg px-2 py-1.5 text-left text-sm ${
                conversation.id === activeId
                  ? 'bg-gray-200 text-gray-900'
                  : 'text-gray-700 hover:bg-gray-200'
              }`}
            >
              {conversation.title}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
