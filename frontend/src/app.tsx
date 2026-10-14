import { Suspense, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, type createBrowserRouter } from "react-router";
import { isApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/overlay";
import { ToastHost } from "@/components/ui/pickers";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) =>
          failureCount < 1 && !(isApiError(error) && error.status >= 400 && error.status < 500),
      },
    },
  });
}

/** Providers shared by the app and by tests. The router is supplied by the caller. */
export function Providers({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AuthProvider>
          {children}
          <ToastHost />
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export function App({
  client,
  router,
}: {
  client: QueryClient;
  router: ReturnType<typeof createBrowserRouter>;
}) {
  return (
    <Providers client={client}>
      <Suspense fallback={null}>
        <RouterProvider router={router} />
      </Suspense>
    </Providers>
  );
}
