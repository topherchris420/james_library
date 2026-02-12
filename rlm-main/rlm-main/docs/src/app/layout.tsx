import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Recursive Language Models",
  description: "A task-agnostic inference paradigm for near-infinite context handling",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 overflow-auto bg-background">
            <div className="max-w-4xl mx-auto px-8 py-16">
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}

