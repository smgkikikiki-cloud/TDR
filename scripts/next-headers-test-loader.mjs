// Node's native ESM resolver does not apply Next's package subpath aliases to
// extensionless `next/headers`; map that import to the package's actual CJS
// entry so the focused test can call the real admin-auth helpers.
export async function resolve(specifier, context, nextResolve) {
  if (specifier === "next/headers") {
    return nextResolve("next/headers.js", context);
  }
  return nextResolve(specifier, context);
}
