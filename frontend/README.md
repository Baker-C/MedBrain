# MedBrain — Frontend

Single-page React app (Vite + React + TypeScript + Tailwind). Talks to the backend only
through its API — see `src/api/` for the endpoint paths and types.

## Setup

```
npm install
cp .env.example .env   # set VITE_API_BASE_URL to the backend base URL
```

## Scripts

- `npm run dev` — start the dev server
- `npm run build` — type-check and build for production
- `npm run lint` — ESLint
- `npm run typecheck` — TypeScript (strict), no emit
- `npm run preview` — preview the production build
