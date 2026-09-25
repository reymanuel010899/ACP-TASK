import type { Metadata } from "next";
import { Inter } from "next/font/google";
import SessionProvider from "@/lib/SessionProvider";
import QueryProvider from "@/lib/QueryProvider";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Console",
  description:
    "Console dashboard — manage your agents, tasks, and ecosystem network.",
};

// Applies the persisted theme before first paint to avoid a theme flash.
// Dark is the default (no data-theme attribute).
//
// This runs before hydration, so by the time React compares the server HTML
// with the DOM the `<html>` element already carries a `data-theme` the server
// never rendered — hence `suppressHydrationWarning` on `<html>` below. It is
// shallow (this element's own attributes only, not its descendants), which is
// exactly the scope of the intentional mismatch.
const themeInitScript = `try{var t=localStorage.getItem("agentio-theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={inter.className}>
        <QueryProvider>
          <SessionProvider>{children}</SessionProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
