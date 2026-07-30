"use client";

// App-wide TanStack Query provider — the server-state cache. Every data read
// goes through a query key; a mutation invalidates only the keys it touches,
// so one action never re-fetches unrelated data. Deduplicates concurrent reads
// of the same key into a single request.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";

export default function QueryProvider({ children }: { children: ReactNode }) {
  // One client per browser session, created lazily so it is never shared
  // across requests on the server.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Data is considered fresh for 15s: navigating back within that
            // window serves from cache with no network call. After that, it
            // revalidates in the background (stale-while-revalidate).
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      {children}
      {process.env.NODE_ENV === "development" && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
