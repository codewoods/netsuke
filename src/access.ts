export interface AccessEnv {
  ENFORCE_ACCESS?: string;
  ACCESS_TEAM_DOMAIN?: string;
  ACCESS_AUD?: string;
}

export type AccessJsonWebKey = JsonWebKey & {
  alg?: string;
  kid?: string;
  use?: string;
};

export interface JsonWebKeySet {
  keys: AccessJsonWebKey[];
}

type AccessResult = { ok: true } | { ok: false; status: 401 | 403; body: string };

type JwtHeader = {
  alg?: string;
  kid?: string;
};

type DecodedJwt = {
  header: JwtHeader;
  payload: Record<string, unknown>;
  signature: Uint8Array;
  signingInput: string;
};

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const CLOCK_TOLERANCE_SECONDS = 60;

const deny = (status: 401 | 403, body: string): AccessResult => ({
  ok: false,
  status,
  body,
});

export const validateAccessRequest = async (
  request: Request,
  env: AccessEnv,
  fetcher: typeof fetch = fetch,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<AccessResult> => {
  /** Verify Cloudflare Access JWTs when production enforcement is enabled. */
  if (env.ENFORCE_ACCESS !== "1") return { ok: true };
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) {
    return deny(403, "access configuration missing");
  }
  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) return deny(401, "unauthorized");
  try {
    const teamDomain = normalizeTeamDomain(env.ACCESS_TEAM_DOMAIN);
    const jwks = await fetchAccessJwks(teamDomain, fetcher);
    const valid = await verifyAccessJwt(
      token,
      jwks,
      env.ACCESS_AUD,
      `https://${teamDomain}`,
      nowSeconds,
    );
    return valid ? { ok: true } : deny(401, "unauthorized");
  } catch {
    return deny(401, "unauthorized");
  }
};

const fetchAccessJwks = async (
  teamDomain: string,
  fetcher: typeof fetch,
): Promise<JsonWebKeySet> => {
  /** Load and shape-check the public keys Cloudflare Access uses for JWTs. */
  const response = await fetcher(`https://${teamDomain}/cdn-cgi/access/certs`);
  if (!response.ok) throw new Error("Access cert lookup failed");
  const data = (await response.json()) as Partial<JsonWebKeySet>;
  if (!Array.isArray(data.keys)) throw new Error("Access cert response invalid");
  return { keys: data.keys };
};

const verifyAccessJwt = async (
  token: string,
  jwks: JsonWebKeySet,
  audience: string,
  issuer: string,
  nowSeconds: number,
): Promise<boolean> => {
  /** Verify the RS256 signature and the minimum Access claims we depend on. */
  const decoded = decodeJwt(token);
  if (decoded.header.alg !== "RS256" || !decoded.header.kid) return false;
  if (!claimsAreValid(decoded.payload, audience, issuer, nowSeconds)) return false;
  const jwk = jwks.keys.find((key) => key.kid === decoded.header.kid);
  if (!jwk) return false;
  const key = await crypto.subtle.importKey(
    "jwk",
    jwk,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    decoded.signature,
    encoder.encode(decoded.signingInput),
  );
};

const decodeJwt = (token: string): DecodedJwt => {
  /** Decode a compact JWT without trusting any of its claims yet. */
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("JWT must have three parts");
  const [headerPart, payloadPart, signaturePart] = parts;
  return {
    header: jsonFromPart<JwtHeader>(headerPart),
    payload: jsonFromPart<Record<string, unknown>>(payloadPart),
    signature: base64UrlToBytes(signaturePart),
    signingInput: `${headerPart}.${payloadPart}`,
  };
};

const claimsAreValid = (
  payload: Record<string, unknown>,
  audience: string,
  issuer: string,
  nowSeconds: number,
): boolean => {
  /** Keep claim validation explicit so failed checks deny by default. */
  const exp = typeof payload.exp === "number" ? payload.exp : NaN;
  const nbf = typeof payload.nbf === "number" ? payload.nbf : undefined;
  if (payload.iss !== issuer) return false;
  if (!audienceMatches(payload.aud, audience)) return false;
  if (!Number.isFinite(exp) || exp + CLOCK_TOLERANCE_SECONDS < nowSeconds) {
    return false;
  }
  if (nbf !== undefined && nbf - CLOCK_TOLERANCE_SECONDS > nowSeconds) {
    return false;
  }
  return true;
};

const jsonFromPart = <T>(part: string): T =>
  JSON.parse(decoder.decode(base64UrlToBytes(part))) as T;

const base64UrlToBytes = (value: string): Uint8Array => {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
};

const audienceMatches = (actual: unknown, expected: string): boolean =>
  actual === expected || (Array.isArray(actual) && actual.includes(expected));

const normalizeTeamDomain = (value: string): string =>
  value.replace(/^https?:\/\//, "").replace(/\/+$/, "");
