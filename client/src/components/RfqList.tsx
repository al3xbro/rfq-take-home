import { useQuery } from '@tanstack/react-query'
import { listRfqs, type RfqSummary } from '../api'

function Confidence({ value }: { value: number }) {
  // Orange through red-orange: the lower the score, the hotter the bar.
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 w-10 overflow-hidden rounded-full bg-raised">
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: value >= 0.85 ? 'var(--color-accent)' : 'var(--color-ember)',
          }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums text-muted">{value.toFixed(2)}</span>
    </div>
  )
}

export function RfqList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const { data, isPending, error } = useQuery({ queryKey: ['rfqs'], queryFn: listRfqs })

  if (isPending) return <p className="p-4 text-sm text-muted">Loading…</p>
  if (error) return <p className="p-4 text-sm text-accent-soft">{(error as Error).message}</p>
  if (!data?.length)
    return (
      <p className="p-6 text-center text-sm text-faint">
        Nothing ingested yet.
        <br />
        Drop an <span className="font-mono text-muted">.eml</span> above to start.
      </p>
    )

  return (
    <ul className="divide-y divide-line">
      {data.map((r: RfqSummary) => {
        const active = r.id === selectedId
        return (
          <li key={r.id}>
            <button
              onClick={() => onSelect(r.id)}
              className={[
                'w-full px-4 py-3 text-left transition',
                active ? 'bg-raised' : 'hover:bg-surface',
              ].join(' ')}
            >
              <div className="flex items-start gap-2">
                <span
                  className={[
                    'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                    r.isRfq ? 'bg-accent' : 'bg-faint',
                  ].join(' ')}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{r.subject || '(no subject)'}</p>
                  <p className="truncate text-xs text-muted">{r.company || r.from}</p>

                  <div className="mt-2 flex items-center gap-3">
                    <Confidence value={r.confidence} />
                    {r.isRfq ? (
                      <span className="text-xs text-faint">{r.lineItemCount} items</span>
                    ) : (
                      <span className="text-xs text-faint">skipped</span>
                    )}
                    {r.warningCount > 0 && (
                      <span className="text-xs text-accent-soft">{r.warningCount} flags</span>
                    )}
                  </div>
                </div>
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
