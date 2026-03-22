// Runtime base path injected by the Rust gateway into index.html.
// Allows the SPA to work under a reverse-proxy path prefix.

declare global {
  interface Window {
    __R.A.I.N._BASE__?: string;
  }
}

/** Gateway path prefix (e.g. "/R.A.I.N."), or empty string when served at root. */
export const basePath: string = (window.__R.A.I.N._BASE__ ?? '').replace(/\/+$/, '');
