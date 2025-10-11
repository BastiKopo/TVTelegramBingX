import { getSigned } from "../../exchange/bingx/accountClient";
import {
  PATH_USER_BALANCE,
  PATH_USER_OPEN_ORDERS,
  PATH_USER_POSITIONS,
} from "../../exchange/bingx/constants";

interface BingxEnvelope {
  code?: number | string;
  msg?: string;
  message?: string;
  data?: unknown;
}

function isEnvelope(payload: unknown): payload is BingxEnvelope {
  return typeof payload === "object" && payload !== null && !Array.isArray(payload);
}

function assertSuccess(endpoint: string, payload: unknown): BingxEnvelope {
  if (!isEnvelope(payload)) {
    throw new Error(`${endpoint} returned an invalid response`);
  }

  const { code, msg, message } = payload;
  if (code !== undefined && code !== null && code !== 0 && code !== "0") {
    const description = msg ?? message ?? String(code);
    throw new Error(`${endpoint} error: ${description}`);
  }

  return payload;
}

export interface ReportSnapshot {
  balance: unknown;
  positions: unknown;
  openOrders?: unknown;
}

export interface ReportOptions {
  symbol?: string;
  includeOpenOrders?: boolean;
}

export async function fetchReport(options: ReportOptions = {}): Promise<ReportSnapshot> {
  const { symbol, includeOpenOrders = false } = options;

  const [balanceResponse, positionsResponse] = await Promise.all([
    getSigned(PATH_USER_BALANCE, {}),
    getSigned(PATH_USER_POSITIONS, symbol ? { symbol } : {}),
  ]);

  const balanceEnvelope = assertSuccess("balance", balanceResponse.json);
  const positionsEnvelope = assertSuccess("positions", positionsResponse.json);

  let openOrdersData: unknown;
  if (includeOpenOrders) {
    try {
      const openOrdersResponse = await getSigned(
        PATH_USER_OPEN_ORDERS,
        symbol ? { symbol } : {}
      );
      const openOrdersEnvelope = assertSuccess("open orders", openOrdersResponse.json);
      openOrdersData = openOrdersEnvelope.data ?? null;
    } catch (error) {
      openOrdersData = undefined;
    }
  }

  return {
    balance: balanceEnvelope.data ?? null,
    positions: positionsEnvelope.data ?? null,
    openOrders: openOrdersData,
  };
}
