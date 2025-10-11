import { BINGX_BASE, PATH_ORDER } from "./constants";

type Payload = Record<string, unknown> | string | null | undefined;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normaliseMethod(method: string | undefined): string {
  const token = (method ?? "").trim().toUpperCase();
  return token || "GET";
}

function normaliseTarget(url: string | undefined, path: string | undefined): string {
  if (url && url.length > 0) return url;
  if (path && path.length > 0) return path;
  return "<unknown>";
}

function extractDetails(payload: Payload): { code: string; message: string } {
  if (isObject(payload)) {
    const code = payload.code;
    const message = payload.msg ?? payload.message;
    return {
      code: code === undefined || code === null || `${code}` === "" ? "" : String(code),
      message:
        message === undefined || message === null || `${message}` === ""
          ? ""
          : String(message),
    };
  }

  if (typeof payload === "string" && payload.trim().length > 0) {
    return { code: "", message: payload };
  }

  return { code: "", message: "" };
}

export function formatBingxError(
  method: string | undefined,
  url: string | undefined,
  payload: Payload,
  options: { requestPath?: string } = {}
): string {
  const methodToken = normaliseMethod(method);
  const target = normaliseTarget(url, options.requestPath);
  const { code, message } = extractDetails(payload);
  const detail = `${code} ${message}`.trim();

  let output = `Failed to contact BingX: ${methodToken} ${target}`;
  if (detail.length > 0) {
    output += ` → ${detail}`;
  }

  const pathForHint = (options.requestPath ?? url ?? "").replace(/\/+$/, "");
  const normalisedPath = pathForHint.replace(/^https?:\/\/[^/]+/i, "");
  if (normalisedPath === PATH_ORDER) {
    output += `\nHint: use POST ${BINGX_BASE}${PATH_ORDER} with x-www-form-urlencoded.`;
  }

  return output;
}
