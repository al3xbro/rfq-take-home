import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { health } from './api'
import { DropZone } from './components/DropZone'
import { RfqList } from './components/RfqList'
import { RfqDetail } from './components/RfqDetail'

export default function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: status } = useQuery({ queryKey: ['health'], queryFn: health, retry: false })

  return (
    <div className="relative z-10 mx-auto max-w-[1400px] px-5 pb-20 pt-8">
      <header className="mb-7 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-ember font-bold text-white">
            R
          </div>
          <div>
            <h1 className="text-base font-semibold leading-tight">RFQ Extractor</h1>
          </div>
        </div>

        {status && (
          <div className="flex items-center gap-2 text-xs text-muted">
            <span
              className={[
                'h-1.5 w-1.5 rounded-full',
                status.apiKeyConfigured ? 'bg-ok' : 'bg-ember',
              ].join(' ')}
              aria-hidden="true"
            />
            <span className="font-mono">{status.model}</span>
            {!status.apiKeyConfigured && (
              <span className="text-ember">· no API key — /ingest returns 503</span>
            )}
          </div>
        )}
      </header>

      <div className="mb-6">
        <DropZone />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(280px,340px)_1fr]">
        <aside className="overflow-hidden rounded-xl border border-line bg-surface lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto">
          <RfqList selectedId={selectedId} onSelect={setSelectedId} />
        </aside>

        <main className="min-w-0">
          {selectedId ? (
            <RfqDetail id={selectedId} />
          ) : (
            <div className="flex min-h-[340px] items-center justify-center rounded-xl border border-dashed border-line/70 text-sm text-faint">
              Select an email to see the extracted requirement
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
