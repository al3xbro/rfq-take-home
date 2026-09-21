# RFQ Extractor — client

React + Vite operator UI. Drag `.eml` files in, click through the extracted
requirements.

```bash
yarn          # install
yarn dev      # http://localhost:5173
yarn build    # typecheck + production bundle
```

Uses **yarn** (`yarn.lock` is committed) — don't mix in npm, or you'll end up
with two lockfiles disagreeing.

Expects the API on `http://localhost:8000`; `vite.config.ts` proxies `/api`,
`/ingest` and `/health` there in dev, so the client stays origin-relative and
needs no configuration.

- **Tailwind v4** — configured in CSS via `@theme` in `src/index.css`, not a
  `tailwind.config.js`.
- **TanStack Query** for fetching and cache invalidation after an ingest.
