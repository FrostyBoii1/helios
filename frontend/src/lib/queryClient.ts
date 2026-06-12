import { QueryClient } from '@tanstack/react-query'

// Periodic refresh keeps staff from working off stale data (spec requirement)
// without yet introducing WebSockets. Tune intervals per-query as needed.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})
