# Facet Client

Angular 21 single-page app for the Facet viewer. It is served by the FastAPI
backend (`python viewer.py`, port 5000) from `client/dist/` after a build.

## Commands

```bash
npm install        # install dependencies

npm run build      # production build to client/dist/
npm start          # dev server on http://localhost:4200 (proxies API to :5000)
npm test           # unit tests (Vitest, via the Angular CLI test runner)
npm run lint       # ESLint
```

During development, run `npm start` alongside `python viewer.py`; the dev
server proxies API calls to the backend on port 5000.
