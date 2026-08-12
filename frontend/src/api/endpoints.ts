/** Backend base URL — set VITE_API_BASE_URL in .env (see .env.example). */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL

/** Endpoint paths, relative to API_BASE_URL. */
export const ENDPOINTS = {
  /** POST (create) · GET (list) */
  conversations: '/conversations',
  /** GET — one conversation with its messages */
  conversation: (id: string) => `/conversations/${id}`,
  /** POST — SSE stream; append `?trace=true` for the single-JSON trace mode */
  query: (id: string) => `/conversations/${id}/query`,
  /** GET — short-lived signed URL for a document's source PDF */
  documentSourceUrl: (id: string) => `/documents/${id}/source-url`,
  /** GET — health probe */
  health: '/health',
} as const
