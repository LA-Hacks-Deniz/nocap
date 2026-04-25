// Owner: DEVIN — Phase 3 task T3.21
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  display: "swap",
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "NoCap.wiki",
  description: "AI agent polygraph for research-grade code.",
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    title: "NoCap.wiki",
    description: "AI agent polygraph for research-grade code.",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "NoCap.wiki",
    description: "AI agent polygraph for research-grade code.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} scroll-smooth antialiased`}>
      <body>{children}</body>
    </html>
  );
}
