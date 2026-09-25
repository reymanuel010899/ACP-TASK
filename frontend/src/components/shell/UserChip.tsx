"use client";

import { useRouter } from "next/navigation";
import { useSession } from "@/lib/SessionProvider";
import { readStoredCsrfToken, revokeWebSession } from "@/lib/agentSession";

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
    // Revoke server-side too, not just locally. The session cookie now
    // outlives this tab by up to 12 hours (`services/session/app.py`), so
    // dropping only the local record would leave a live, usable session
    // behind on the machine -- exactly what someone clicking "Log out"
    // means to prevent. Captured before `clearSession()`, which wipes the
    // CSRF token this call needs.
    const csrfToken = readStoredCsrfToken();
    if (csrfToken) {
      // Deliberately not awaited: a failed revocation must never trap the
      // user in a signed-in UI. The local session goes regardless.
      void revokeWebSession(csrfToken).catch(() => {});
    }
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
