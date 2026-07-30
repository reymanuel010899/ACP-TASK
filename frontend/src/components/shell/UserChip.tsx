"use client";

import { useRouter } from "next/navigation";
import { useSession } from "@/lib/SessionProvider";

/**
 * Truncates a base64 principal id for display on the new-device / no-username
 * login path (e.g. "3f8aK9xQ...mZ2p"). Short ids are shown in full.
 */
function displayPrincipalId(principalId: string): string {
  if (principalId.length <= 14) return principalId;
  return `${principalId.slice(0, 8)}…${principalId.slice(-4)}`;
}

/** Avatar + user info block used in the shared top bar (from the Organizations design). */
export default function UserChip() {
  const { session, clearSession } = useSession();
  const router = useRouter();

  // AppShell (frontend unit U5) gates every route this renders under on an
  // active session, so `session` is always present here in practice -- this
  // component has no unauthenticated rendering path to design for.
  const principalId = session?.principalId ?? "";
  const displayName = session?.username || displayPrincipalId(principalId);

  function handleLogout() {
    // Client-only: sessions are stateless, self-expiring assertions with no
    // server-side revocation endpoint in this design, so "logging out" is
    // just discarding the local session and sending the user back to /login.
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-center">
      <div className="box-border w-[32px] shrink-0 h-[32px] bg-[#D99975] rounded-full"></div>
      <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
        <div className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
          {displayName}
        </div>
        <button
          type="button"
          onClick={handleLogout}
          className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] cursor-pointer border-0 bg-transparent p-0 underline"
        >
          Log out
        </button>
      </div>
    </div>
  );
}
