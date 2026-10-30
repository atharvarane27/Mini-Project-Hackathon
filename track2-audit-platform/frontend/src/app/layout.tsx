import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Finstack | Banking Audit Operations",
  description: "Evidence-first banking audit operations dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
