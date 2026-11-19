import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CiteVerify – Scientific Claim Verification",
  description:
    "Upload an academic document to verify scientific claims against cited sources. " +
    "Results are intended to assist human reviewers only.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
          <span className="text-blue-600 font-bold text-xl">CiteVerify</span>
          <span className="text-gray-400 text-sm">Scientific Claim Verification</span>
        </header>
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-2 text-xs text-amber-800">
          ⚠ <strong>Disclaimer:</strong> This tool is designed to <em>assist</em> human reviewers.
          Results are <strong>never</strong> a final academic judgment. Always verify independently.
        </div>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
