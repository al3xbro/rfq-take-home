/** Types mirror the server's output contract (see ../server/rfq_extractor/schema.py). */

export interface Customer {
  name: string | null
  email: string | null
  phone: string | null
  company: string | null
}

export interface RequestMeta {
  dueDate: string | null
  priority: 'low' | 'medium' | 'high' | 'urgent'
  specialInstructions: string | null
}

export interface LineItem {
  partNumber: string
  manufacturer: string | null
  description: string | null
  quantity: number
  targetPrice: number | null
  notes: string | null
}

export type IngestResult =
  | {
      isRfq: true
      confidence: number
      customer: Customer
      request: RequestMeta
      lineItems: LineItem[]
      warnings: string[]
    }
  | { isRfq: false; confidence: number; reason: string }

/** Telemetry the server stores alongside the result. Deliberately not part of
 *  the /ingest contract — it is only exposed on the detail endpoint. */
export interface Extras {
  subject?: string
  from?: string
  sent_date?: string | null
  source_chars?: number
  image_count?: number
  total_ms?: number
  classification_confidence?: number
  resolve_chunks?: number
  stages?: Record<string, { status: string; ms: number }>
  tool_calls?: { tool: string; args: unknown }[]
  candidates?: { part_hint: string; qty_expr: string; source_span: string }[]
  verification?: {
    unverified_parts: number
    unverified_quantities: number
    unverifiable_parts: number
    restored_items: number
  }
}

export interface RfqSummary {
  id: string
  receivedAt: string
  filename: string | null
  subject: string
  from: string
  isRfq: boolean
  confidence: number
  company: string | null
  lineItemCount: number
  warningCount: number
}

export interface RfqRecord {
  id: string
  receivedAt: string
  filename: string | null
  result: IngestResult
  extras: Extras
}

export class ApiError extends Error {
  // Written out longhand: this tsconfig enables `erasableSyntaxOnly`, which
  // disallows TypeScript parameter properties.
  status: number
  hint?: string

  constructor(status: number, message: string, hint?: string) {
    super(message)
    this.status = status
    this.hint = hint
  }
}

async function failFrom(res: Response): Promise<ApiError> {
  // The server returns {error, message, hint?} for its own failures. Anything
  // else (a proxy error page, say) still needs to surface as something readable.
  try {
    const body = await res.json()
    return new ApiError(res.status, body.message ?? body.error ?? res.statusText, body.hint)
  } catch {
    return new ApiError(res.status, res.statusText || `request failed (${res.status})`)
  }
}

export async function listRfqs(): Promise<RfqSummary[]> {
  const res = await fetch('/api/rfqs')
  if (!res.ok) throw await failFrom(res)
  return res.json()
}

export async function getRfq(id: string): Promise<RfqRecord> {
  const res = await fetch(`/api/rfqs/${id}`)
  if (!res.ok) throw await failFrom(res)
  return res.json()
}

/** Post one .eml. The server takes the raw bytes; no multipart needed. */
export async function ingest(file: File): Promise<IngestResult> {
  const res = await fetch('/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'message/rfc822' },
    body: await file.arrayBuffer(),
  })
  if (!res.ok) throw await failFrom(res)
  return res.json()
}

export async function health(): Promise<{ status: string; model: string; apiKeyConfigured: boolean }> {
  const res = await fetch('/health')
  if (!res.ok) throw await failFrom(res)
  return res.json()
}
