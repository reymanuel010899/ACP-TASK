"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import Sidebar, { type NavKey } from "@/components/shell/Sidebar";
import TopBar from "@/components/shell/TopBar";
import ClientConsole from "@/components/client/ClientConsole";
import { useSession } from "@/lib/SessionProvider";

/**
 * Shared page frame: full-viewport row with the app sidebar, a scrollable
 * center column (shared top bar + content), and an optional right panel.
 * `topBarAction` is the only part of the top bar that varies per page.
 *
 * Also the session gate (frontend unit U5, R7) for every route that renders
 * through it -- every page under `src/app/` except `/login` does, so
 * enforcing "no session -> redirect to /login" here covers the whole
 * protected surface from one place rather than per-page. `useSession()` is a
 * client hook (backed by `localStorage`, unavailable during SSR), so this
 * check can only run client-side; while signed out this renders `null`
 * instead of the shell so the authenticated UI never flashes before the
 * redirect lands. Note the server-rendered/first-hydration snapshot from
 * `SessionProvider` is always the signed-out shape by design (see its own
 * `getServerSnapshot` note) and resolves to the real session right after
 * mount, same as every other `useSession()` consumer in this app.
 *
 * The redirect effect gates on `isHydrated`, not just `!session`: on the
 * very first client commit, `session` is null because it's still the
 * SSR/hydration placeholder, not because the user is actually signed out.
 * Since this component is a DESCENDANT of `SessionProvider`, its passive
 * effects fire before `SessionProvider`'s own (React flushes passive
 * effects bottom-up) -- so without the `isHydrated` guard, this would
 * `router.replace("/login")` on every reload using the placeholder, one
 * beat before `SessionProvider` corrects it with the real, still-valid
 * `sessionStorage` session.
 */
export default function AppShell({
  active,
  topBarAction,
  children,
  rightPanel,
}: {
  active: NavKey;
  topBarAction?: ReactNode;
  children: ReactNode;
  rightPanel?: ReactNode;
}) {
  const { session, isHydrated } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (isHydrated && !session) {
      router.replace("/login");
    }
  }, [isHydrated, session, router]);

  if (!session) {
    return null;
  }

  return (
    <div className="box-border w-full h-screen flex flex-row gap-0 justify-start items-start bg-[var(--ag-bg)] overflow-hidden">
      <Sidebar active={active} />
      <div className="box-border [flex:1_1_0] min-w-0 h-full overflow-y-auto flex flex-col gap-0 justify-start items-start">
        <TopBar action={topBarAction} />
        {children}
      </div>
      {rightPanel}
      <ClientConsole />
    </div>
  );
}
