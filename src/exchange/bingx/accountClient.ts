import { createHmac } from "node:crypto";
import { BINGX_BASE } from "./constants";

const API_KEY = process.env.BINGX_API_KEY ?? "";
const API_SECRET = process.env.BINGX_API_SECRET ?? "";
const RECV_WINDOW = process.env.BINGX_RECV_WINDOW ?? "5000";

function normaliseParams(params: Record<string, string | number | undefined>): Record<string, string> {
  return Object.keys(params)
    .filter((key) => params[key] !== undefined)
    .reduce<Record<string, string>>((acc, key) => {
      const value = params[key];
      acc[key] = String(value);
      return acc;
    }, {});
}

function signQuery(params: Record<string, string>): string {
  const sortedKeys = Object.keys(params).sort();
  const query = sortedKeys.map((key) => `${key}=${params[key]}`).join("&");
  const signature = createHmac("sha256", API_SECRET).update(query).digest("hex");
  return `${query}&signature=${signature}`;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch (error) {
    return null;
  }
}

function redactSignature(text: string): string {
  return text.replace(/signature=[0-9a-f]+/gi, "signature=<redacted>");
}

export interface SignedResponse {
  status: number;
  text: string;
  json: unknown;
}

export async function getSigned(
  path: string,
  params: Record<string, string | number | undefined>
): Promise<SignedResponse> {
  if (!API_KEY || !API_SECRET) {
    throw new Error("BingX API credentials are not configured");
  }
  if (!globalThis.fetch) {
    throw new Error("Global fetch API is not available in this runtime");
  }

  const baseParams = normaliseParams({
    ...params,
    recvWindow: RECV_WINDOW,
    timestamp: Date.now(),
  });
  const queryString = signQuery(baseParams);
  const url = `${BINGX_BASE}${path}?${queryString}`;
  const redactedUrl = redactSignature(url);

  console.log("→ GET", redactedUrl);

  const response = await globalThis.fetch(url, {
    method: "GET",
    headers: {
      "X-BX-APIKEY": API_KEY,
    },
  });

  const text = await response.text();
  console.log("HTTP", response.status, text);

  return {
    status: response.status,
    text,
    json: typeof text === "string" ? safeJson(text) : null,
  };
}
