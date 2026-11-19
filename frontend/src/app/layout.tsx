import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CiteVerify",
  description:
    "Scientific claim and citation verification — assists human reviewers.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 font-sans">
        {/* ── Disclaimer banner ── */}
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-xs text-amber-800 text-center">
          ⚠️{" "}
          <strong>CiteVerify assists human reviewers.</strong> Output is{" "}
          <strong>not</strong> a final academic judgment. Always review results
          yourself.
        </div>

        {/* ── Top nav ── */}
        <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3">
          <span className="text-blue-600 font-bold text-lg tracking-tight">
            CiteVerify
          </span>
          <span className="text-gray-400 text-sm">
            Scientific Claim Verification
          </span>
        </header>

        <main className="max-w-4xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
