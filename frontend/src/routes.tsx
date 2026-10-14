import { lazy } from "react";
import { Link, type RouteObject } from "react-router";
import { RedirectIfSignedIn, RequireAuth } from "@/lib/auth";
import { shell } from "@/copy/shell";
import { AppShell } from "@/components/shell/app-shell";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/display";

const LoginPage = lazy(() => import("@/features/login/login-page"));
const OverviewPage = lazy(() => import("@/features/overview/overview-page"));
const ProductsPage = lazy(() => import("@/features/products/products-page"));
const ProductFormPage = lazy(() => import("@/features/products/product-form-page"));
const ProductDetailPage = lazy(() => import("@/features/products/product-detail-page"));
const StockPage = lazy(() => import("@/features/stock/stock-page"));
const SalesPage = lazy(() => import("@/features/sales/sales-page"));
const SaleEntryPage = lazy(() => import("@/features/sales/sale-entry-page"));
const SaleDetailPage = lazy(() => import("@/features/sales/sale-detail-page"));
const PurchasesPage = lazy(() => import("@/features/purchases/purchases-page"));
const PurchaseNewPage = lazy(() => import("@/features/purchases/purchase-new-page"));
const PurchaseDetailPage = lazy(() => import("@/features/purchases/purchase-detail-page"));

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
          { path: "products", element: <ProductsPage /> },
          { path: "products/new", element: <ProductFormPage /> },
          { path: "products/:id", element: <ProductDetailPage /> },
          { path: "products/:id/edit", element: <ProductFormPage /> },
          { path: "stock", element: <StockPage /> },
          { path: "sales", element: <SalesPage /> },
          { path: "sales/new", element: <SaleEntryPage /> },
          { path: "sales/:id", element: <SaleDetailPage /> },
          { path: "purchases", element: <PurchasesPage /> },
          { path: "purchases/new", element: <PurchaseNewPage /> },
          { path: "purchases/:id", element: <PurchaseDetailPage /> },
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
