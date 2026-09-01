# V7 Owner Console

SvelteKit management UI for tenant owners and platform operators. It talks to
the Flask backend through the `/api` proxy during local development.

## Local development

Run the Flask API from the repository root on port `5055`, then:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite proxy forwards `/api/*` to the origin
configured in `V7_BACKEND_ORIGIN` (default: `http://127.0.0.1:5055`).

## Production boundary

Serve the compiled SvelteKit app and Flask API behind the same HTTPS origin.
Route `/api/*` to Flask after removing the `/api` prefix. This keeps the
session cookie same-origin and avoids enabling permissive admin CORS.

Do not expose the Flask admin API directly to arbitrary browser origins.
