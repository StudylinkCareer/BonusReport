/**
 * SAVE TO: frontend/app/layout.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\layout.tsx)
 *
 * Root layout. Wraps every page in <AuthProvider>, which:
 *   - On first render, calls /api/auth/me to determine login state
 *   - Redirects to /login if not logged in
 *   - Renders a UserBadge (top-right) showing the current user + Logout
 *
 * The /login page itself is exempted from the redirect, so logged-out
 * users land there without bouncing.
 */

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "./_components/AuthProvider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "StudyLink BonusReport",
  description: "StudyLink staff bonus calculation and reporting",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
