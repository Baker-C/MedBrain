export function ChatArea() {
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 py-3">
        <span className="text-lg font-semibold text-gray-800">MedBrain</span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-6 px-4">
        <h1 className="text-3xl font-semibold text-gray-800">What do you want to look up?</h1>
        <input
          type="text"
          placeholder="Ask about the drug labeling"
          className="w-full max-w-2xl rounded-full border border-gray-300 bg-gray-100 px-5 py-3.5 text-gray-800 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-amber-300"
        />
      </div>
      <footer className="px-4 pb-3 text-center text-xs text-gray-500">
        MedBrain answers from FDA drug labeling and cites its sources. It does not give medical
        advice.
      </footer>
    </div>
  )
}
