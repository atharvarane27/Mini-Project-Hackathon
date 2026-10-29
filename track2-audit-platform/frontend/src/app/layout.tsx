import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AuditForge | Banking Audit & Workflow Platform",
  description:
    "Concurrent Banking Audit, Record Resolution & Rule-Driven Workflow Platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-slate-950 text-slate-100 min-h-screen">
        {children}
      </body>
    </html>
  );
}
