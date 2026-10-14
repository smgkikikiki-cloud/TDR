import { gunzipSync } from "node:zlib";

/** Decompress a private backup without parsing and reserializing its JSON tokens. */
export function decompressPrivateBackupJson(gzipBytes: Uint8Array): Buffer {
  return gunzipSync(gzipBytes);
}
