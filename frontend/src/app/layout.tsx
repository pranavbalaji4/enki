import type { Metadata } from "next";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import "./globals.css";
import { AppStateProvider } from "@/components/AppState";
import Sidebar from "@/components/Sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Enki",
  description: "A tutor that learns how you learn.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${newsreader.variable} h-full antialiased`}>
      <body className="h-full font-sans">
        <AppStateProvider>
          <div className="flex h-full">
            <Sidebar />
            <main className="flex-1 min-w-0 h-full overflow-hidden">{children}</main>
          </div>
        </AppStateProvider>
      </body>
    </html>
  );
}
