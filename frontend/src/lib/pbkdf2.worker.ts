/**
 * Web Worker entry point for the PBKDF2-SHA256 KDF step (frontend unit U1).
 *
 * Runs the 600,000-iteration derivation off the main thread so it never
 * blocks UI interactivity. Talks to `agentCrypto.ts`'s `deriveKek` via a
 * small request/response message protocol; the actual derivation logic
 * lives in `pbkdf2DeriveBits` (agentCrypto.ts) so the worker and the
 * non-worker fallback path share one implementation.
 */

import { pbkdf2DeriveBits } from "./agentCrypto";

interface Pbkdf2WorkerRequest {
  requestId: number;
  password: Uint8Array;
  salt: Uint8Array;
  iterations: number;
  keyLengthBytes: number;
}

interface Pbkdf2WorkerResponse {
  requestId: number;
  ok: boolean;
  result?: Uint8Array;
  error?: string;
}

self.onmessage = async (event: MessageEvent<Pbkdf2WorkerRequest>) => {
  const { requestId, password, salt, iterations, keyLengthBytes } = event.data;
  try {
    const result = await pbkdf2DeriveBits(password, salt, iterations, keyLengthBytes);
    const response: Pbkdf2WorkerResponse = { requestId, ok: true, result };
    (self as unknown as Worker).postMessage(response, [result.buffer]);
  } catch (err) {
    const response: Pbkdf2WorkerResponse = {
      requestId,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    };
    (self as unknown as Worker).postMessage(response);
  }
};
