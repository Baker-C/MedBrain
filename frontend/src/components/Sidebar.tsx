import { ConversationList } from './ConversationList'

interface SidebarProps {
  open: boolean
  onToggle: () => void
}

export function Sidebar({ open, onToggle }: SidebarProps) {
  return (
    <aside
      className={`flex flex-col border-r border-gray-200 bg-gray-50 transition-[width] duration-200 ${
        open ? 'w-64' : 'w-14'
      }`}
    >
      <div className={`flex p-2 ${open ? 'justify-end' : 'justify-center'}`}>
        <button
          type="button"
          onClick={onToggle}
          aria-label={open ? 'Collapse sidebar' : 'Open sidebar'}
          className="rounded-lg p-2 text-gray-500 hover:bg-gray-200"
        >
          <PanelIcon />
        </button>
      </div>
      <div className="px-2">
        <button
          type="button"
          className={`flex w-full items-center gap-2 rounded-lg p-2 text-sm text-gray-700 hover:bg-gray-200 ${
            open ? '' : 'justify-center'
          }`}
        >
          <NewChatIcon />
          {open && <span>New chat</span>}
        </button>
      </div>
      {open && <ConversationList />}
    </aside>
  )
}

function PanelIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  )
}

function NewChatIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5 shrink-0"
    >
      <path d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
      <path d="M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
    </svg>
  )
}
