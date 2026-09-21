import { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, ingest } from '../api'

type Status = 'pending' | 'done' | 'error'
interface Job { name: string; status: Status; detail?: string }

export function DropZone() {
  const [dragging, setDragging] = useState(false)
  const [jobs, setJobs] = useState<Job[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const { mutateAsync } = useMutation({
    mutationFn: ingest,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['rfqs'] }),
  })

  const send = useCallback(
    async (files: File[]) => {
      if (!files.length) return
      setJobs(files.map((f) => ({ name: f.name, status: 'pending' as Status })))

      // Each ingest is several model calls; run them together and let the
      // server's async handlers overlap rather than queueing client-side.
      await Promise.allSettled(
        files.map(async (file) => {
          try {
            await mutateAsync(file)
            setJobs((j) => j.map((x) => (x.name === file.name ? { ...x, status: 'done' } : x)))
          } catch (err) {
            const detail =
              err instanceof ApiError ? `${err.message}${err.hint ? ` — ${err.hint}` : ''}` : String(err)
            setJobs((j) => j.map((x) => (x.name === file.name ? { ...x, status: 'error', detail } : x)))
          }
        }),
      )
    },
    [mutateAsync],
  )

  const pending = jobs.filter((j) => j.status === 'pending').length
  const failed = jobs.filter((j) => j.status === 'error')

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          void send(Array.from(e.dataTransfer.files))
        }}
        onClick={() => inputRef.current?.click()}
        className={[
          'cursor-pointer rounded-xl border border-dashed px-6 py-10 text-center transition',
          dragging
            ? 'border-accent bg-accent/10 shadow-[0_0_0_4px_rgba(255,122,24,0.08)]'
            : 'border-line bg-surface/60 hover:border-faint hover:bg-surface',
        ].join(' ')}
      >
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-ember">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 16V4M12 4l-4 4M12 4l4 4" />
            <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
          </svg>
        </div>
        <p className="text-sm font-medium">
          {dragging ? 'Drop to ingest' : 'Drop .eml files here'}
        </p>
        <p className="mt-1 text-xs text-muted">or click to browse — several at once is fine</p>

        <input
          ref={inputRef}
          type="file"
          accept=".eml,message/rfc822"
          multiple
          className="hidden"
          onChange={(e) => {
            void send(Array.from(e.target.files ?? []))
            e.target.value = ''
          }}
        />
      </div>

      {jobs.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {pending > 0 && (
            <p className="text-xs text-muted">
              <span className="mr-2 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent align-middle" />
              Extracting {pending} email{pending > 1 ? 's' : ''} — this takes ~20s each
            </p>
          )}
          {failed.map((j) => (
            <p key={j.name} className="rounded-md border border-ember-dim bg-ember/10 px-3 py-2 text-xs text-accent-soft">
              <span className="font-mono">{j.name}</span> — {j.detail}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
