/**
 * Browser crypto primitives for the AgentTrust Vault (frontend unit U1).
 *
 * A byte-compatible TypeScript port of `vault/crypto.py`'s envelope
 * encryption chain, plus ed25519 keygen/sign for the principal identity.
 *
 * Chain (mirrors vault/crypto.py):
 *     Master Password -> PBKDF2-SHA256 (600,000 iterations) -> KEK
 *     KEK wraps -> DEK (per-user Data Encryption Key, stored ENCRYPTED)
 *     DEK encrypts -> credentials + principal private key
 *
 * The KEK is never stored anywhere; it exists only transiently in the
 * browser. All symmetric encryption uses XSalsa20-Poly1305 ("secretbox"),
 * an AEAD construction: decryption with the wrong key throws instead of
 * returning garbage.
 *
 * On-wire blob shape is byte-identical to `vault/crypto.py::build_keyring_blob`
 * / `unlock_keyring_blob`: `{encrypted_dek, salt, nonce, kdf, kdf_params,
 * encrypted_private_key}`, all binary fields as standard base64 strings, so a
 * blob written by either language is readable by the other.
 *
 * PBKDF2 runs via WebCrypto's `crypto.subtle.deriveBits`, dispatched to a Web
 * Worker (`pbkdf2.worker.ts`) in the browser so 600,000 iterations never
 * blocks the UI thread. Outside a browser (SSR, tests) there is no `Worker`
 * global, so `deriveKek` falls back to running the same WebCrypto call
 * directly -- still non-blocking there because Node's WebCrypto PBKDF2
 * implementation itself does not run synchronously on the JS event loop.
 */

import { ed25519 } from "@noble/curves/ed25519.js";
import { xsalsa20poly1305 } from "@noble/ciphers/salsa.js";
import { randomBytes as nobleRandomBytes, utf8ToBytes } from "@noble/ciphers/utils.js";

// ---------------------------------------------------------------------------
// Constants (mirror vault/crypto.py)
// ---------------------------------------------------------------------------

export const DEFAULT_KDF = "pbkdf2-sha256";
export const DEFAULT_ITERATIONS = 600_000;
export const KEY_SIZE = 32; // nacl.secret.SecretBox.KEY_SIZE
export const NONCE_SIZE = 24; // nacl.secret.SecretBox.NONCE_SIZE
export const SALT_SIZE = 16;

const SUPPORTED_KDFS: readonly string[] = [DEFAULT_KDF];

// ---------------------------------------------------------------------------
// Errors (mirror vault/crypto.py's small, explicit hierarchy)
// ---------------------------------------------------------------------------

export class VaultCryptoError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VaultCryptoError";
  }
}

/** Decryption failed authentication (wrong password/key or tampering). */
export class VaultAuthError extends VaultCryptoError {
  constructor(
    message = "decryption failed: wrong key or tampered ciphertext",
  ) {
    super(message);
    this.name = "VaultAuthError";
  }
}

/** Keyring blob declares a KDF this implementation does not support. */
export class UnsupportedKDFError extends VaultCryptoError {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedKDFError";
  }
}

// ---------------------------------------------------------------------------
// Base64 encoding helpers (blobs travel as JSON, so bytes are base64 strings)
// ---------------------------------------------------------------------------

export function b64encode(raw: Uint8Array): string {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(raw).toString("base64");
  }
  let binary = "";
  for (let i = 0; i < raw.length; i++) {
    binary += String.fromCharCode(raw[i]);
  }
  return btoa(binary);
}

export function b64decode(text: string): Uint8Array {
  if (typeof Buffer !== "undefined") {
    return new Uint8Array(Buffer.from(text, "base64"));
  }
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

// ---------------------------------------------------------------------------
// ed25519 keygen / sign (the principal identity keypair)
// ---------------------------------------------------------------------------

export interface Ed25519KeyPair {
  /** 32-byte ed25519 seed. Secret material -- never transmitted in the clear. */
  privateKey: Uint8Array;
  /** 32-byte ed25519 public key. This is the `principal_id`'s raw form. */
  publicKey: Uint8Array;
}

export function generateKeypair(): Ed25519KeyPair {
  const { secretKey, publicKey } = ed25519.keygen();
  return { privateKey: secretKey, publicKey };
}

export function publicKeyFromPrivate(privateKey: Uint8Array): Uint8Array {
  return ed25519.getPublicKey(privateKey);
}

export function sign(message: Uint8Array, privateKey: Uint8Array): Uint8Array {
  return ed25519.sign(message, privateKey);
}

export function verify(
  signature: Uint8Array,
  message: Uint8Array,
  publicKey: Uint8Array,
): boolean {
  return ed25519.verify(signature, message, publicKey);
}

// ---------------------------------------------------------------------------
// KDF (PBKDF2-SHA256 via WebCrypto, dispatched to a Web Worker in-browser)
// ---------------------------------------------------------------------------

/**
 * Low-level PBKDF2-SHA256 bit derivation. Pure WebCrypto, no environment
 * assumptions beyond a `crypto.subtle` global -- safe to call from either
 * the main thread (fallback) or `pbkdf2.worker.ts` (the real dispatch
 * target in the browser).
 */
export async function pbkdf2DeriveBits(
  password: Uint8Array,
  salt: Uint8Array,
  iterations: number,
  keyLengthBytes: number,
): Promise<Uint8Array> {
  const subtle = globalThis.crypto.subtle;
  const keyMaterial = await subtle.importKey(
    "raw",
    password as BufferSource,
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await subtle.deriveBits(
    { name: "PBKDF2", salt: salt as BufferSource, iterations, hash: "SHA-256" },
    keyMaterial,
    keyLengthBytes * 8,
  );
  return new Uint8Array(bits);
}

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

let pbkdf2Worker: Worker | null = null;
let pbkdf2RequestCounter = 0;

function isWorkerAvailable(): boolean {
  return typeof Worker !== "undefined" && typeof window !== "undefined";
}

function getPbkdf2Worker(): Worker {
  if (!pbkdf2Worker) {
    pbkdf2Worker = new Worker(new URL("./pbkdf2.worker.ts", import.meta.url), {
      type: "module",
    });
  }
  return pbkdf2Worker;
}

function deriveKekViaWorker(
  password: Uint8Array,
  salt: Uint8Array,
  iterations: number,
  keyLengthBytes: number,
): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const worker = getPbkdf2Worker();
    const requestId = ++pbkdf2RequestCounter;

    const handleMessage = (event: MessageEvent<Pbkdf2WorkerResponse>) => {
      if (event.data.requestId !== requestId) return;
      worker.removeEventListener("message", handleMessage);
      worker.removeEventListener("error", handleError);
      if (event.data.ok && event.data.result) {
        resolve(event.data.result);
      } else {
        reject(new VaultCryptoError(event.data.error ?? "PBKDF2 worker failed"));
      }
    };
    const handleError = (event: ErrorEvent) => {
      worker.removeEventListener("message", handleMessage);
      worker.removeEventListener("error", handleError);
      reject(new VaultCryptoError(`PBKDF2 worker error: ${event.message}`));
    };

    worker.addEventListener("message", handleMessage);
    worker.addEventListener("error", handleError);

    const request: Pbkdf2WorkerRequest = {
      requestId,
      password,
      salt,
      iterations,
      keyLengthBytes,
    };
    worker.postMessage(request);
  });
}

/**
 * Derive the Key Encryption Key from the master password.
 *
 * Deterministic for the same (password, salt, iterations) -- mirrors
 * `vault/crypto.py::derive_kek`. The KEK must never be stored: derive it on
 * demand, use it, discard it.
 *
 * In a browser, the PBKDF2 work is dispatched to `pbkdf2.worker.ts` so the
 * 600,000-iteration derivation never blocks the UI thread. Outside a
 * browser (SSR, tests, no `Worker` global) it runs directly via WebCrypto.
 */
export async function deriveKek(
  password: string,
  salt: Uint8Array,
  iterations: number = DEFAULT_ITERATIONS,
): Promise<Uint8Array> {
  const passwordBytes = utf8ToBytes(password);
  if (isWorkerAvailable()) {
    return deriveKekViaWorker(passwordBytes, salt, iterations, KEY_SIZE);
  }
  return pbkdf2DeriveBits(passwordBytes, salt, iterations, KEY_SIZE);
}

/** Terminate the cached PBKDF2 worker, if one was spawned. Test/cleanup use. */
export function terminatePbkdf2Worker(): void {
  if (pbkdf2Worker) {
    pbkdf2Worker.terminate();
    pbkdf2Worker = null;
  }
}

export function generateSalt(): Uint8Array {
  return nobleRandomBytes(SALT_SIZE);
}

export function generateDek(): Uint8Array {
  return nobleRandomBytes(KEY_SIZE);
}

// ---------------------------------------------------------------------------
// Authenticated encryption (XSalsa20-Poly1305 / NaCl SecretBox)
// ---------------------------------------------------------------------------

interface Sealed {
  ciphertext: Uint8Array;
  nonce: Uint8Array;
}

function seal(plaintext: Uint8Array, key: Uint8Array): Sealed {
  const nonce = nobleRandomBytes(NONCE_SIZE);
  const ciphertext = xsalsa20poly1305(key, nonce).encrypt(plaintext);
  return { ciphertext, nonce };
}

function open(ciphertext: Uint8Array, nonce: Uint8Array, key: Uint8Array): Uint8Array {
  try {
    return xsalsa20poly1305(key, nonce).decrypt(ciphertext);
  } catch {
    throw new VaultAuthError();
  }
}

/** Encrypt the DEK under the KEK. Returns {ciphertext, nonce}. */
export function wrapDek(dek: Uint8Array, kek: Uint8Array): Sealed {
  return seal(dek, kek);
}

/** Recover the DEK. Throws VaultAuthError if the KEK is wrong. */
export function unwrapDek(
  encryptedDek: Uint8Array,
  nonce: Uint8Array,
  kek: Uint8Array,
): Uint8Array {
  return open(encryptedDek, nonce, kek);
}

/** Encrypt credential/key material under the DEK. Returns {ciphertext, nonce}. */
export function encryptData(plaintext: Uint8Array, dek: Uint8Array): Sealed {
  return seal(plaintext, dek);
}

/** Decrypt data. Throws VaultAuthError on wrong DEK or tampering. */
export function decryptData(
  ciphertext: Uint8Array,
  nonce: Uint8Array,
  dek: Uint8Array,
): Uint8Array {
  return open(ciphertext, nonce, dek);
}

// ---------------------------------------------------------------------------
// Keyring blob helpers (the client-side envelope work)
// ---------------------------------------------------------------------------

export interface KeyringBlob {
  encrypted_dek: string;
  salt: string;
  nonce: string;
  kdf: string;
  kdf_params: { iterations: number };
  encrypted_private_key: string;
}

/**
 * Validate KDF metadata from a keyring blob (forward-compat check).
 *
 * Throws UnsupportedKDFError for unknown kdf values or malformed params, so
 * that blobs written by a future Vault version are rejected loudly instead
 * of being mis-derived. Mirrors vault/crypto.py::validate_kdf.
 */
export function validateKdf(kdf: unknown, kdfParams: unknown): void {
  if (typeof kdf !== "string" || !SUPPORTED_KDFS.includes(kdf)) {
    throw new UnsupportedKDFError(
      `unsupported kdf ${JSON.stringify(kdf)} (supported: ${SUPPORTED_KDFS.join(", ")})`,
    );
  }
  if (typeof kdfParams !== "object" || kdfParams === null) {
    throw new UnsupportedKDFError("kdf_params must be an object");
  }
  const iterations = (kdfParams as { iterations?: unknown }).iterations;
  if (typeof iterations !== "number" || !Number.isInteger(iterations) || iterations < 1) {
    throw new UnsupportedKDFError("kdf_params.iterations must be a positive integer");
  }
}

/**
 * Build the wrapped keyring blob stored in the Vault.
 *
 * Returns {blob, dek}. The blob is JSON-safe (bytes are base64) and
 * contains only wrapped material:
 *     {encrypted_dek, salt, nonce, kdf, kdf_params, encrypted_private_key}
 * The private key is encrypted under the DEK with its own nonce, stored
 * combined as nonce||ciphertext inside encrypted_private_key. Mirrors
 * vault/crypto.py::build_keyring_blob field-for-field.
 */
export async function buildKeyringBlob(
  password: string,
  privateKey: Uint8Array,
  iterations: number = DEFAULT_ITERATIONS,
): Promise<{ blob: KeyringBlob; dek: Uint8Array }> {
  const salt = generateSalt();
  const kek = await deriveKek(password, salt, iterations);
  const dek = generateDek();
  const { ciphertext: encryptedDek, nonce } = wrapDek(dek, kek);
  const { ciphertext: pkCiphertext, nonce: pkNonce } = encryptData(privateKey, dek);

  const combined = new Uint8Array(pkNonce.length + pkCiphertext.length);
  combined.set(pkNonce, 0);
  combined.set(pkCiphertext, pkNonce.length);

  const blob: KeyringBlob = {
    encrypted_dek: b64encode(encryptedDek),
    salt: b64encode(salt),
    nonce: b64encode(nonce),
    kdf: DEFAULT_KDF,
    kdf_params: { iterations },
    encrypted_private_key: b64encode(combined),
  };
  return { blob, dek };
}

/**
 * Unlock a fetched keyring blob with the master password.
 *
 * Returns {dek, privateKey}. Throws VaultAuthError on a wrong password
 * (authenticated encryption -- no partial/garbage data is ever returned)
 * and UnsupportedKDFError for blobs written with an unknown KDF. Mirrors
 * vault/crypto.py::unlock_keyring_blob.
 */
export async function unlockKeyringBlob(
  password: string,
  blob: KeyringBlob,
): Promise<{ dek: Uint8Array; privateKey: Uint8Array }> {
  validateKdf(blob.kdf, blob.kdf_params);
  const iterations = blob.kdf_params.iterations;
  const salt = b64decode(blob.salt);
  const kek = await deriveKek(password, salt, iterations);
  const dek = unwrapDek(b64decode(blob.encrypted_dek), b64decode(blob.nonce), kek);

  const combined = b64decode(blob.encrypted_private_key);
  const pkNonce = combined.slice(0, NONCE_SIZE);
  const pkCiphertext = combined.slice(NONCE_SIZE);
  const privateKey = decryptData(pkCiphertext, pkNonce, dek);
  return { dek, privateKey };
}
