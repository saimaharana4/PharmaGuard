import { NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const development = process.env.NODE_ENV !== "production";
  const policy = [
    "default-src 'self'", `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'`, "img-src 'self' data:", "font-src 'self'",
    "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'",
    "frame-ancestors 'none'", ...(development ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({request: {headers}});
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
}
export const config = {matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]};
