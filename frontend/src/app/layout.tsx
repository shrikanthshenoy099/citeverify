import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'CiteVerify',
  description:
    'Scientific claim and citation verification – research assistant only, not a final academic judgment.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 font-sans">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
          <span className="text-xl font-semibold tracking-tight">CiteVerify</span>
          <span className="text-xs bg-amber-100 text-amber-800 border border-amber-300 rounded px-2 py-0.5">
            Research assistant · not a final academic judgment
          </span>
        </header>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  )
}
