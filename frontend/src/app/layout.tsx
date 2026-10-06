import type { Metadata } from "next";
import { Figtree, Literata } from "next/font/google";
import "./globals.css";
import { AppStateProvider } from "@/components/AppState";
import Sidebar from "@/components/Sidebar";

const figtree = Figtree({ variable: "--font-figtree", subsets: ["latin"] });
const literata = Literata({ variable: "--font-literata", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Enki",
  description: "How you learn, read from your conversations with Claude.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${figtree.variable} ${literata.variable} h-full antialiased`}>
      <body className="h-full font-sans">
        <AppStateProvider>
          <div className="flex h-full flex-col md:flex-row">
            <Sidebar />
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
          </div>
        </AppStateProvider>
      </body>
    </html>
  );
}
