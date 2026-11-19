'use client'

import { useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { uploadDocument } from '@/lib/api'

export default function HomePage() {
  const router = useRouter()
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleSubmit = useCallback(async () => {
    setError(null)
    if (!file && !text.trim()) {
      setError('Please upload a file or paste some text.')
      return
    }
    setLoading(true)
    try {
      const { doc_id } = await uploadDocument(file ?? text)
      router.push(`/results/${doc_id}`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [file, text, router])

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Verify a Document</h1>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-900">
        <strong>Important:</strong> This tool assists human reviewers. All verdicts with
        "needs human review" must be checked by a qualified reviewer before any action is taken.
      </div>

      {/* File upload */}
      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
        <p className="font-medium text-sm text-gray-700">Option 1 – Upload a PDF or DOCX</p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx"
          onChange={e => {
            setFile(e.target.files?.[0] ?? null)
            setText('')
          }}
          className="text-sm"
        />
        {file && (
          <p className="text-xs text-gray-500">
            Selected: <span className="font-mono">{file.name}</span>
          </p>
        )}
      </div>

      <div className="text-center text-xs text-gray-400">— or —</div>

      {/* Text paste */}
      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
        <p className="font-medium text-sm text-gray-700">Option 2 – Paste text</p>
        <textarea
          className="w-full border border-gray-300 rounded p-2 text-sm font-mono h-40 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400"
          placeholder="Paste the text of your paper here..."
          value={text}
          onChange={e => {
            setText(e.target.value)
            setFile(null)
            if (fileRef.current) fileRef.current.value = ''
          }}
        />
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">{error}</p>
      )}

      <button
        onClick={handleSubmit}
        disabled={loading}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold py-3 rounded-lg transition"
      >
        {loading ? 'Submitting…' : 'Verify Document'}
      </button>
    </div>
  )
}
