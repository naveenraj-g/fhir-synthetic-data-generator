"use client";

import { ActivityIcon, ListChecksIcon, MoonIcon, SearchIcon, SparklesIcon, SunIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Suspense } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useBackendStatus } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Generate", icon: SparklesIcon, match: (p: string) => p === "/" },
  { href: "/jobs", label: "Jobs", icon: ListChecksIcon, match: (p: string) => p.startsWith("/jobs") },
  { href: "/explore", label: "Find codes", icon: SearchIcon, match: (p: string) => p.startsWith("/explore") },
];

function BackendStatus() {
  const { data, isError, isPending } = useBackendStatus();
  const state = isPending ? "checking" : isError || !data?.ok ? "down" : "up";
  const dot = { checking: "bg-muted-foreground", up: "bg-success", down: "bg-destructive" }[state];
  const label = {
    checking: "Checking the API…",
    up: "API connected",
    down: isError ? "Cannot reach the API. Start it with `just dev` in backend/." : "API reachable but not ready",
  }[state];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="text-muted-foreground inline-flex items-center gap-2 text-xs" role="status">
            <span className={cn("size-2 rounded-full", dot)} />
            <span className="hidden sm:inline">{state === "up" ? "API" : state === "down" ? "API offline" : "API…"}</span>
          </span>
        }
      />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      <SunIcon className="hidden dark:block" />
      <MoonIcon className="dark:hidden" />
    </Button>
  );
}

function NavLinks({ pathname }: { pathname: string }) {
  return (
    <nav className="flex items-center gap-1" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon, match }) => (
        <Link
          key={href}
          href={href}
          aria-current={match(pathname) ? "page" : undefined}
          className={cn(buttonVariants({ variant: match(pathname) ? "secondary" : "ghost" }), "gap-1.5")}
        >
          <Icon />
          {label}
        </Link>
      ))}
    </nav>
  );
}

/** usePathname() is a runtime value, so it sits behind Suspense; the links render (unhighlighted) in the static shell. */
function ActiveNav() {
  return <NavLinks pathname={usePathname()} />;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="bg-background/80 sticky top-0 z-30 border-b backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-6 px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="bg-primary text-primary-foreground grid size-7 place-items-center rounded-md">
              <ActivityIcon className="size-4" />
            </span>
            <span className="hidden sm:inline">FHIR Synthetic Data</span>
          </Link>
          <Suspense fallback={<NavLinks pathname="" />}>
            <ActiveNav />
          </Suspense>
          <div className="ml-auto flex items-center gap-2">
            <BackendStatus />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
