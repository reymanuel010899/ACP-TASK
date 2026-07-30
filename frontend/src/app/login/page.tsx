"use client";

/**
 * Pre-auth login screen (frontend unit U4). Deliberately has no
 * `AppShell`/`Sidebar` -- there is no authenticated identity yet for the
 * shell to reflect.
 */

import LoginForm from "./LoginForm";
import { useSession } from "@/lib/SessionProvider";

export default function LoginPage() {
  const { notice, clearNotice } = useSession();

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[var(--ag-bg)] px-[16px]">
      <div className="w-full max-w-[400px] box-border flex flex-col gap-[20px] rounded-[16px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[32px]">
        <div className="flex flex-col gap-[4px]">
          <h1 className="text-[20px] font-semibold text-[var(--ag-text)]">Sign in</h1>
          <p className="text-[13px] text-[var(--ag-text-secondary)]">
            Access your Console account.
          </p>
        </div>

        {notice === "expired" && (
          <div
            role="alert"
            className="flex items-center justify-between gap-[8px] rounded-[10px] border border-[var(--ag-orange)] bg-[var(--ag-orange)]/10 px-[12px] py-[10px] text-[13px] text-[var(--ag-text)]"
          >
            <span>Your session expired. Please log in again.</span>
            <button
              type="button"
              onClick={clearNotice}
              aria-label="Dismiss"
              className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-[12px] text-[var(--ag-text-secondary)] underline"
            >
              Dismiss
            </button>
          </div>
        )}

        <LoginForm />
      </div>
    </div>
  );
}
