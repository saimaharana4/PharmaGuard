import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
const endpoints = new Set(["health", "ready", "version", "investigate", "session"]);
let cachedIdentity: {token: string; expires: number} | undefined;

async function boundedBody(request: NextRequest): Promise<string | undefined> {
  if (!request.body) return undefined;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16000) {
        await reader.cancel();
        throw new RangeError("Request is too large");
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(bytes);
}

function sameOrigin(origin: string | null, host: string | null): boolean {
  try { return !!origin && new URL(origin).host === host; } catch { return false; }
}

async function upstreamHeaders(audience: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = {"Content-Type": "application/json"};
  if (process.env.API_AUTH_MODE === "cloudrun") {
    if (!audience.startsWith("https://") || !new URL(audience).hostname.endsWith(".run.app")) throw new Error("Invalid API audience");
    if (!cachedIdentity || cachedIdentity.expires < Date.now()) {
      const response = await fetch(`http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(audience)}&format=full`, {
        headers: {"Metadata-Flavor":"Google"}, signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error("Service identity unavailable");
      cachedIdentity = {token: await response.text(), expires: Date.now() + 45 * 60 * 1000};
    }
    headers.Authorization = `Bearer ${cachedIdentity.token}`;
  }
  return headers;
}

async function proxy(request: NextRequest, context: {params: Promise<{endpoint: string}>}) {
  const {endpoint} = await context.params;
  if (!endpoints.has(endpoint) || (["investigate", "session"].includes(endpoint)) !== (request.method === "POST")) {
    return NextResponse.json({error: {code: "NOT_FOUND", message: "Unknown endpoint."}}, {status: 404});
  }
  const requestId = crypto.randomUUID();
  const origin = request.headers.get("origin");
  if (request.method === "POST" && !sameOrigin(origin, request.headers.get("host"))) {
    return NextResponse.json({error: {code:"ORIGIN_REJECTED", message:"Use the chatbot workspace to submit questions.",request_id:requestId}}, {status:403});
  }
  if (Number(request.headers.get("content-length") ?? "0") > 16000) {
    return NextResponse.json({error: {code: "INVALID_REQUEST", message: "Request is too large.", request_id: requestId}}, {status: 413});
  }
  try {
    const body = request.method === "POST" ? await boundedBody(request) : undefined;
    const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
    const headers = await upstreamHeaders(base);
    const sessionToken = request.cookies.get("pg_session")?.value;
    if (sessionToken) headers["X-Session-Token"] = sessionToken;
    const upstream = await fetch(`${base}/${endpoint}`, {
      method: request.method, headers,
      body, cache: "no-store", signal: AbortSignal.timeout(85000),
    });
    const response = new NextResponse(await upstream.text(), {status: upstream.status, headers: {
      "Content-Type": "application/json", "Cache-Control": "no-store",
      "X-Request-ID": upstream.headers.get("X-Request-ID") ?? requestId,
    }});
    const renewed = upstream.headers.get("X-Session-Token");
    if (renewed) response.cookies.set("pg_session", renewed, {
      httpOnly: true, secure: process.env.COOKIE_SECURE === "true" || request.nextUrl.protocol === "https:", sameSite: "strict",
      path: "/", maxAge: 3600,
    });
    if (upstream.status === 401) response.cookies.delete("pg_session");
    return response;
  } catch (error) {
    if (error instanceof RangeError) {
      return NextResponse.json({error: {code: "INVALID_REQUEST", message: "Request is too large.", request_id: requestId}}, {status: 413});
    }
    return NextResponse.json({error: {code: "API_UNAVAILABLE", message: "The investigation service is temporarily unavailable.", request_id: requestId}}, {status: 503});
  }
}
export {proxy as GET, proxy as POST};
