import { describe, expect, test } from "bun:test";

import {
  validateAccessRequest,
  type AccessEnv,
  type JsonWebKeySet,
} from "../src/access";

const encoder = new TextEncoder();

const b64url = (bytes: Uint8Array): string =>
  btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");

const jsonPart = (value: unknown): string =>
  b64url(encoder.encode(JSON.stringify(value)));

const accessEnv = (): AccessEnv => ({
  ENFORCE_ACCESS: "1",
  ACCESS_TEAM_DOMAIN: "team.cloudflareaccess.com",
  ACCESS_AUD: "app-aud",
});

const signedToken = async (
  payloadPatch: Record<string, unknown> = {},
): Promise<{ token: string; jwks: JsonWebKeySet }> => {
  /**
   * Generate a real RS256 token/JWKS pair so the test proves signature
   * verification, not just JWT string parsing.
   */
  const keys = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const publicJwk = await crypto.subtle.exportKey("jwk", keys.publicKey);
  const kid = "test-key";
  const header = jsonPart({ alg: "RS256", kid, typ: "JWT" });
  const now = Math.floor(Date.now() / 1000);
  const payload = jsonPart({
    aud: ["app-aud"],
    exp: now + 300,
    iss: "https://team.cloudflareaccess.com",
    nbf: now - 30,
    ...payloadPatch,
  });
  const signingInput = `${header}.${payload}`;
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    keys.privateKey,
    encoder.encode(signingInput),
  );
  return {
    token: `${signingInput}.${b64url(new Uint8Array(signature))}`,
    jwks: { keys: [{ ...publicJwk, alg: "RS256", kid, use: "sig" }] },
  };
};

const jwksFetch = (jwks: JsonWebKeySet): typeof fetch =>
  (async () => Response.json(jwks)) as typeof fetch;

describe("validateAccessRequest", () => {
  test("allows local requests when enforcement is disabled", async () => {
    const result = await validateAccessRequest(new Request("https://x.test"), {});
    expect(result.ok).toBe(true);
  });

  test("rejects enforced requests without a token", async () => {
    const result = await validateAccessRequest(
      new Request("https://x.test"),
      accessEnv(),
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(401);
  });

  test("rejects enforced requests without Access configuration", async () => {
    const result = await validateAccessRequest(new Request("https://x.test"), {
      ENFORCE_ACCESS: "1",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(403);
  });

  test("accepts a signed Access JWT for the configured audience", async () => {
    const { token, jwks } = await signedToken();
    const request = new Request("https://x.test", {
      headers: { "cf-access-jwt-assertion": token },
    });
    const result = await validateAccessRequest(
      request,
      accessEnv(),
      jwksFetch(jwks),
    );
    expect(result.ok).toBe(true);
  });

  test("rejects a signed Access JWT for the wrong audience", async () => {
    const { token, jwks } = await signedToken({ aud: ["other-aud"] });
    const request = new Request("https://x.test", {
      headers: { "cf-access-jwt-assertion": token },
    });
    const result = await validateAccessRequest(
      request,
      accessEnv(),
      jwksFetch(jwks),
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.status).toBe(401);
  });
});
