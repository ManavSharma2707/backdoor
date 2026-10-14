import { lazy } from "react";
import { Link, type RouteObject } from "react-router";
import { RedirectIfSignedIn, RequireAuth } from "@/lib/auth";
import { shell } from "@/copy/shell";
import { AppShell } from "@/components/shell/app-shell";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/display";

const LoginPage = lazy(() => import("@/features/login/login-page"));
const OverviewPage = lazy(() => import("@/features/overview/overview-page"));

function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <>
      <PageHeader title={title} />
      <p className="max-w-xl text-base text-text-2">{body}</p>
      <Link to="/" className="mt-4 inline-block">
        <Button>{shell.placeholder.action}</Button>
      </Link>
    </>
  );
}

function NotFound() {
  return (
    <>
      <PageHeader title={shell.notFound.title} />
      <Link to="/">
        <Button>{shell.notFound.action}</Button>
      </Link>
    </>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/login",
    element: (
      <RedirectIfSignedIn>
        <LoginPage />
      </RedirectIfSignedIn>
    ),
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <OverviewPage /> },
          {
            path: "plan/*",
            element: <Placeholder {...shell.placeholder.plan} />,
          },
          {
            path: "insights",
            element: <Placeholder {...shell.placeholder.insights} />,
          },
          {
            path: "assistant",
            element: <Placeholder {...shell.placeholder.assistant} />,
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
