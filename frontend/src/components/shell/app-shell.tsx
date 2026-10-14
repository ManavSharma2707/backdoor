import { Suspense, useEffect, useState, useSyncExternalStore } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  CalendarCheck,
  ChartLine,
  LayoutGrid,
  Menu as MenuIcon,
  MessageSquare,
  Package,
  Receipt,
  Search,
  Settings as SettingsIcon,
  Truck,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useAuth, useSession } from "@/lib/auth";
import { get, serverStatus } from "@/lib/api";
import { formatDayMonth, todayIso, weekStartOf } from "@/lib/format";
import { useDebounced, useSlashToSearch } from "@/lib/hooks";
import { common } from "@/copy/common";
import { shell } from "@/copy/shell";
import type { Page, Product } from "@/types/models";
import { Button } from "@/components/ui/button";
import { Banner, Skeleton } from "@/components/ui/display";
import { Drawer, Menu } from "@/components/ui/overlay";
import { CommandPalette } from "@/components/ui/pickers";

type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean };

const NAV: NavItem[] = [
  { to: "/", label: shell.nav.overview, icon: LayoutGrid, end: true },
  { to: "/plan", label: shell.nav.plan, icon: CalendarCheck },
  { to: "/products", label: shell.nav.products, icon: Package },
  { to: "/sales", label: shell.nav.sales, icon: Receipt },
  { to: "/purchases", label: shell.nav.purchases, icon: Truck },
  { to: "/stock", label: shell.nav.stock, icon: Boxes },
  { to: "/insights", label: shell.nav.insights, icon: ChartLine },
  { to: "/settings", label: shell.nav.settings, icon: SettingsIcon },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { tenant } = useSession();
  return (
    <div className="flex h-full flex-col bg-surface">
      <div className="px-4 pt-4 pb-3">
        <div className="text-md leading-5 font-semibold">{tenant.name}</div>
        {tenant.is_synthetic ? (
          <div className="mt-1 text-xs text-text-3">{shell.demoLabel}</div>
        ) : null}
      </div>
      <nav aria-label={shell.nav.label} className="flex-1 overflow-y-auto pb-4">
        <ul>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    "flex h-10 items-center gap-3 border-l-2 px-4 text-base font-medium",
                    isActive
                      ? "border-primary bg-primary-soft text-primary"
                      : "border-transparent text-text-2 hover:bg-surface-2 hover:text-text",
                  )
                }
              >
                <Icon size={16} strokeWidth={1.5} aria-hidden="true" />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

function ServerStatusBanner() {
  const status = useSyncExternalStore(serverStatus.subscribe, serverStatus.get);
  const queryClient = useQueryClient();
  if (status === "ok") return null;
  return (
    <div className="px-4 pt-4 md:px-6">
      {status === "waking" ? (
        <Banner tone="warning">{shell.serverWaking}</Banner>
      ) : (
        <Banner
          tone="error"
          action={
            <Button
              size="sm"
              onClick={() => {
                serverStatus.set("ok");
                void queryClient.invalidateQueries();
              }}
            >
              {shell.retry}
            </Button>
          }
        >
          {shell.serverDown}
        </Banner>
      )}
    </div>
  );
}

function TopBar({ onMenu, onSearch }: { onMenu: () => void; onSearch: () => void }) {
  const { user, tenant } = useSession();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const week = formatDayMonth(weekStartOf(todayIso()));
  return (
    <header className="no-print flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4 md:px-6">
      <Button
        variant="ghost"
        size="sm"
        className="px-2 lg:hidden"
        aria-label={shell.menu}
        onClick={onMenu}
      >
        <MenuIcon size={18} strokeWidth={1.5} />
      </Button>
      <div className="min-w-0 flex-1 truncate text-base font-medium lg:hidden">{tenant.name}</div>
      <div className="hidden text-base text-text-2 lg:block">{shell.weekOf(week)}</div>
      <div className="hidden flex-1 lg:block" />
      <button
        type="button"
        onClick={onSearch}
        className="hidden h-9 w-64 items-center gap-2 rounded-sm border border-border-strong bg-surface px-3 text-left text-base text-text-3 hover:bg-surface-2 md:flex"
      >
        <Search size={14} strokeWidth={1.5} aria-hidden="true" />
        <span className="flex-1 truncate">{shell.search.hint}</span>
        <kbd className="font-sans text-xs text-text-3">{shell.search.shortcut}</kbd>
      </button>
      <Button
        variant="ghost"
        size="sm"
        className="px-2 md:hidden"
        aria-label={shell.search.button}
        onClick={onSearch}
      >
        <Search size={18} strokeWidth={1.5} />
      </Button>
      <Button
        variant="secondary"
        size="sm"
        className="shrink-0"
        onClick={() => navigate("/assistant")}
      >
        <MessageSquare size={14} strokeWidth={1.5} aria-hidden="true" />
        {shell.assistant}
      </Button>
      <Menu
        trigger={
          <Button variant="ghost" size="sm" aria-label={shell.userMenu} className="max-w-40">
            <span className="hidden truncate md:inline">{user.full_name}</span>
            <span className="md:hidden" aria-hidden="true">
              {user.full_name.slice(0, 1)}
            </span>
          </Button>
        }
        items={[
          { label: shell.account, onSelect: () => navigate("/settings?tab=account") },
          { label: shell.signOut, onSelect: () => void logout() },
        ]}
      />
    </header>
  );
}

export function AppShell() {
  const { tenant } = useSession();
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, 200);
  useSlashToSearch();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const products = useQuery({
    queryKey: ["palette-products", debounced],
    queryFn: () => get<Page<Product>>("/products", { q: debounced, page_size: 6 }),
    enabled: paletteOpen && debounced.trim().length >= 2,
  });

  const pageItems = NAV.filter((item) =>
    item.label.toLowerCase().includes(query.trim().toLowerCase()),
  ).map((item) => ({
    id: `page-${item.to}`,
    label: item.label,
    onSelect: () => navigate(item.to),
  }));

  return (
    <div className="min-h-dvh">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-sm focus:bg-surface focus:px-3 focus:py-2"
      >
        {common.skipToContent}
      </a>
      <aside className="no-print fixed inset-y-0 left-0 z-20 hidden w-56 border-r border-border lg:block">
        <Sidebar />
      </aside>
      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} title={tenant.name} side="left">
        <Sidebar onNavigate={() => setDrawerOpen(false)} />
      </Drawer>
      <div className="flex min-h-dvh flex-col lg:pl-56">
        <TopBar onMenu={() => setDrawerOpen(true)} onSearch={() => setPaletteOpen(true)} />
        {tenant.is_synthetic ? (
          <div className="flex h-7 shrink-0 items-center bg-info-soft px-4 text-xs text-text md:px-6">
            {shell.demoStrip}
          </div>
        ) : null}
        <ServerStatusBanner />
        <main id="content" tabIndex={-1} className="flex-1 px-4 py-6 outline-none md:px-6">
          <div className="max-w-[1360px]">
            <Suspense fallback={<RouteSkeleton />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={(open) => {
          setPaletteOpen(open);
          if (!open) setQuery("");
        }}
        pages={pageItems}
        products={(products.data?.items ?? []).map((product) => ({
          id: `product-${product.id}`,
          label: product.name,
          meta: product.sku,
          onSelect: () => navigate(`/products/${product.id}`),
        }))}
        onQueryChange={setQuery}
        searching={products.isFetching}
        copy={common.commandPalette}
      />
    </div>
  );
}

export function RouteSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-4 w-72" />
      <Skeleton className="mt-6 h-64 w-full" />
    </div>
  );
}
