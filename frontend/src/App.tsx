import { useState } from 'react'
import { ChatArea } from './components/ChatArea'
import { Sidebar } from './components/Sidebar'
import { ConversationProvider } from './state/ConversationStore'

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <ConversationProvider>
      <div className="flex h-screen flex-col">
        <header className="border-b border-amber-300 bg-amber-100 px-4 py-2 text-center text-sm font-medium text-amber-900">
          Document-lookup tool for professionals - not medical advice
        </header>
        <div className="flex min-h-0 flex-1">
          <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen((open) => !open)} />
          <main className="min-w-0 flex-1">
            <ChatArea />
          </main>
        </div>
      </div>
    </ConversationProvider>
  )
}

export default App
