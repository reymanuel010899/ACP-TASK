"use client";

/**
 * Pre-auth registration screen (frontend unit U7). Deliberately has no
 * `AppShell`/`Sidebar` -- there is no authenticated identity yet for the
 * shell to reflect, same as `login/page.tsx`.
 */

import Link from "next/link";
import RegisterForm from "./RegisterForm";

export default function RegisterPage() {
  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[var(--ag-bg)] px-[16px]">
      <div className="w-full max-w-[400px] box-border flex flex-col gap-[20px] rounded-[16px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[32px]">
        <div className="flex flex-col gap-[4px]">
          <h1 className="text-[20px] font-semibold text-[var(--ag-text)]">Create your account</h1>
          <p className="text-[13px] text-[var(--ag-text-secondary)]">
            Your identity is generated on this device. There is no password
            recovery -- keep your password and principal_id safe.
          </p>
        </div>

        <RegisterForm />

        <p className="text-[13px] text-[var(--ag-text-secondary)]">
          Already have an account?{" "}
          <Link href="/login" className="text-[var(--ag-purple-light)] underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
