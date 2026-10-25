# 0004. FastAPI instead of http.server; the plugin API and /health need no password

- Status: Accepted
- Date: 2026-10-25

## Context

The plugin API is a FastAPI router, as in dr-st7789v. The skeleton's web service was a
`ThreadingHTTPServer` with its own routing, security headers, same-origin and JSON checks,
and optional Basic authentication on every route. The FSP calls the plugin API without
credentials, and the Docker healthcheck calls `/health`.

## Decision

- `dr_ssd1306.server.web.create_app` is a FastAPI app with the same routes and answers:
  `400 {"error": ...}` for invalid input, `401`, `403` for a cross-origin write, `415` for a
  write that isn't JSON, bodies of at most 8192 bytes, and the same security headers on
  every response.
- With `DR_SSD1306_PASSWORD` set, Basic authentication protects every route except `/health`
  and `/plugin/*`.
- The I²C writer still runs in its own thread, started and stopped with the app.

## Consequences

- The plugin API can be called by anyone who reaches the port; an FSP's Operate on it
  starts an event. Keep the port off untrusted networks, as before.
- Through the FSP, `/api/plugins/display_ssd1306/*` reaches the display's `/api/*` only
  without a password.
