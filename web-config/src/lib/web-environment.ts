export type WebAuthSettings = { supabaseUrl: string; publishableKey: string };

export function publicAuthSettings(
  env: Record<string, string | undefined>,
): WebAuthSettings | null {
  const url = env.NEXT_PUBLIC_SUPABASE_URL;
  const key = env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) return null;
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== "/" ||
      parsed.search ||
      parsed.hash
    )
      return null;
    if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) {
      // Legacy anon keys are supported. The backend still verifies user JWTs;
      // decoding this public key only prevents accidentally exposing a secret.
      const parts = key.split(".");
      if (parts.length !== 3 || parts.some((part) => !/^[A-Za-z0-9_-]+$/.test(part))) return null;
      const claims = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (claims.role !== "anon") return null;
    }
    return { supabaseUrl: parsed.origin, publishableKey: key };
  } catch {
    return null;
  }
}
