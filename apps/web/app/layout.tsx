import type { Metadata } from "next";
import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "PharmaGuard AI | Evidence workspace",
  description: "Evidence-grounded drug-safety signal investigation with verifiable sources.",
};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
