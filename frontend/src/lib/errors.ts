/** The user-facing text for a thrown value, whatever it turned out to be. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}
