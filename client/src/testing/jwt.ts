// Shared token fixture for the specs that exercise AuthService.token. That
// getter now reads the JWT's own `exp`, so an opaque placeholder string no
// longer passes for a session token: anything the client cannot read as a live
// JWT is treated as expired and never sent.

/** Build a token shaped like the server's, expiring the given seconds from now. */
export function makeJwt(expiresInSeconds: number, claims: Record<string, unknown> = {}): string {
  const payload = { sub: '_legacy', ...claims, exp: Math.floor(Date.now() / 1000) + expiresInSeconds };
  return `header.${btoa(JSON.stringify(payload))}.signature`;
}
