import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Home Health RN Platform",
  description:
    "AI-assisted home health documentation. Every suggestion carries evidence and confidence; every decision is made by an RN.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
