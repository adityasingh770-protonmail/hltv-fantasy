import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Fantasy Lab · HLTV team builder",
  description: "Compare five budget-aware Counter-Strike fantasy lineups.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
