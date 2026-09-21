import { useQuery } from '@tanstack/react-query'
import { getRfq, type LineItem } from '../api'

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-faint">{label}</dt>
      <dd className={value ? 'text-sm' : 'text-sm italic text-faint'}>{value || 'null'}</dd>
    </div>
  )
}

function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-surface">
      {title && (
        <h2 className="border-b border-line px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted">
          {title}
        </h2>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function RfqDetail({ id }: { id: string }) {
  const { data, isPending, error } = useQuery({ queryKey: ['rfq', id], queryFn: () => getRfq(id) })

  if (isPending) return <p className="p-6 text-sm text-muted">Loading…</p>
  if (error) return <p className="p-6 text-sm text-accent-soft">{(error as Error).message}</p>

  const { result, extras } = data
  const v = extras.verification
  const needsReview = !!v && (v.unverified_parts > 0 || v.restored_items > 0)

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold">{extras.subject || '(no subject)'}</h1>
            <p className="font-mono text-xs text-muted">{extras.from}</p>
          </div>
          <div className="text-right">
            <span
              className={[
                'rounded-full border px-2.5 py-0.5 text-xs font-semibold',
                result.isRfq ? 'border-accent text-accent' : 'border-faint text-faint',
              ].join(' ')}
            >
              {result.isRfq ? 'RFQ' : 'skipped'}
            </span>
            <p className="mt-1.5 font-mono text-sm tabular-nums">
              {result.confidence.toFixed(2)}
              <span className="ml-1 text-xs text-faint">confidence</span>
            </p>
          </div>
        </div>
      </Card>

      {!result.isRfq ? (
        <Card title="Why it was skipped">
          <p className="text-sm">{result.reason}</p>
        </Card>
      ) : (
        <>
          {result.warnings.length > 0 && (
            <section className="rounded-xl border border-ember-dim bg-ember/[0.07] p-5">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-accent-soft">
                {result.warnings.length} thing{result.warnings.length > 1 ? 's' : ''} to check
                {needsReview && <span className="ml-2 text-ember">· needs review</span>}
              </h2>
              <ul className="space-y-2">
                {result.warnings.map((w, i) => (
                  <li key={i} className="flex gap-2.5 text-sm text-ink/90">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ember" aria-hidden="true" />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <Card title="Customer & request">
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Field label="Name" value={result.customer.name} />
              <Field label="Company" value={result.customer.company} />
              <Field label="Email" value={result.customer.email} />
              <Field label="Phone" value={result.customer.phone} />
              <Field label="Due date" value={result.request.dueDate} />
              <Field label="Priority" value={result.request.priority} />
              <div className="col-span-2">
                <Field label="Special instructions" value={result.request.specialInstructions} />
              </div>
            </dl>
          </Card>

          <section className="overflow-hidden rounded-xl border border-line bg-surface">
            <h2 className="border-b border-line px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted">
              Line items ({result.lineItems.length})
            </h2>
            {result.lineItems.length === 0 ? (
              <p className="p-6 text-center text-sm text-faint">No line items extracted.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-faint">
                      <th className="px-5 py-2 font-medium">Part</th>
                      <th className="px-3 py-2 font-medium">Manufacturer</th>
                      <th className="px-3 py-2 text-right font-medium">Qty</th>
                      <th className="px-3 py-2 text-right font-medium">Target</th>
                      <th className="px-5 py-2 font-medium">Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/70">
                    {result.lineItems.map((li: LineItem, i: number) => (
                      <tr key={i} className="align-top hover:bg-raised/50">
                        <td className="px-5 py-3">
                          <span className="font-mono font-medium text-accent">{li.partNumber}</span>
                          {li.description && (
                            <p className="mt-0.5 text-xs text-muted">{li.description}</p>
                          )}
                        </td>
                        <td className="px-3 py-3 text-muted">{li.manufacturer || '—'}</td>
                        <td className="px-3 py-3 text-right font-mono tabular-nums">
                          {li.quantity ? li.quantity.toLocaleString() : (
                            <span className="text-ember">0</span>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right font-mono tabular-nums text-muted">
                          {li.targetPrice ?? '—'}
                        </td>
                        <td className="max-w-xs px-5 py-3 text-xs text-muted">{li.notes || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      {/* Operator context — stored alongside the result, deliberately not part
          of the /ingest contract. */}
      <Card title="Processing">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Field
            label="Confidence ceiling"
            value={
              extras.classification_confidence != null
                ? `${extras.classification_confidence.toFixed(2)} (classifier)`
                : null
            }
          />
          <Field label="Email sent" value={extras.sent_date ?? null} />
          <Field label="Total time" value={extras.total_ms ? `${extras.total_ms} ms` : null} />
          <Field
            label="Source"
            value={`${extras.source_chars ?? 0} chars${extras.image_count ? `, ${extras.image_count} image(s)` : ''}`}
          />
        </dl>

        {extras.stages && (
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(extras.stages).map(([name, s]) => (
              <span
                key={name}
                className="rounded-md border border-line bg-raised px-2 py-1 font-mono text-xs text-muted"
              >
                {name} {s.ms}ms
                {s.status !== 'ok' && <span className="ml-1 text-ember">{s.status}</span>}
              </span>
            ))}
            {(extras.resolve_chunks ?? 1) > 1 && (
              <span className="rounded-md border border-accent/40 bg-accent/10 px-2 py-1 font-mono text-xs text-accent-soft">
                {extras.resolve_chunks} chunks in parallel
              </span>
            )}
          </div>
        )}

        {v && (
          <div className="mt-4 border-t border-line pt-4">
            <p className="mb-2 text-xs uppercase tracking-wide text-faint">Verification</p>
            <div className="flex flex-wrap gap-4 text-xs">
              <span className={v.unverified_parts ? 'text-ember' : 'text-muted'}>
                {v.unverified_parts} possible invention{v.unverified_parts === 1 ? '' : 's'}
              </span>
              <span className={v.restored_items ? 'text-ember' : 'text-muted'}>
                {v.restored_items} dropped &amp; restored
              </span>
              <span className="text-muted">{v.unverified_quantities} unverified qty</span>
              <span className="text-muted">{v.unverifiable_parts} unverifiable (image)</span>
            </div>
          </div>
        )}

        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-faint hover:text-muted">
            Raw contract JSON — exactly what POST /ingest returned
          </summary>
          <pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-line bg-base p-3 font-mono text-xs text-muted">
            {JSON.stringify(result, null, 2)}
          </pre>
        </details>
      </Card>
    </div>
  )
}
