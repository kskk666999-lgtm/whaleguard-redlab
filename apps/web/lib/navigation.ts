const SAFE_REDIRECT_BASE = "http://whaleguard.local";
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;
const MAX_REDIRECT_LENGTH = 2048;
const MAX_DECODE_DEPTH = 8;

function hasUnsafeRedirectSyntax(value: string): boolean {
  return (
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    CONTROL_CHARACTERS.test(value)
  );
}

export function safeInternalPath(value: string | null | undefined, fallback = "/dashboard"): string {
  if (!value || value.length > MAX_REDIRECT_LENGTH) return fallback;

  let probe = value;
  let stable = false;
  for (let depth = 0; depth < MAX_DECODE_DEPTH; depth += 1) {
    if (hasUnsafeRedirectSyntax(probe)) return fallback;
    let decoded: string;
    try {
      decoded = decodeURIComponent(probe);
    } catch {
      return fallback;
    }
    if (decoded === probe) {
      stable = true;
      break;
    }
    probe = decoded;
  }
  if (!stable || hasUnsafeRedirectSyntax(probe)) return fallback;

  try {
    const base = new URL(SAFE_REDIRECT_BASE);
    const resolved = new URL(value, base);
    if (resolved.origin !== base.origin) return fallback;
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  } catch {
    return fallback;
  }
}
