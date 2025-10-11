export type Intent = "LONG_OPEN" | "LONG_CLOSE" | "SHORT_OPEN" | "SHORT_CLOSE";

type OrderType = "Market" | "Limit";
type PositionSide = "LONG" | "SHORT";

function emojiAndTitle(intent: Intent | string): { emoji: string; title: string } {
  switch ((intent || "").toUpperCase()) {
    case "LONG_OPEN":
      return { emoji: "🟢", title: "Buy" };
    case "SHORT_OPEN":
      return { emoji: "🔴", title: "Sell" };
    case "LONG_CLOSE":
      return { emoji: "⚪", title: "Close Long" };
    case "SHORT_CLOSE":
      return { emoji: "⚫", title: "Close Short" };
    default:
      return { emoji: "⚪", title: "Signal" };
  }
}

function autoTradeStr(on: boolean): string {
  return on ? "On" : "Off";
}

function tsStr(d?: Date): string {
  const dt = d ?? new Date();
  const pad = (n: number) => n.toString().padStart(2, "0");
  const Y = dt.getFullYear();
  const M = pad(dt.getMonth() + 1);
  const D = pad(dt.getDate());
  const h = pad(dt.getHours());
  const m = pad(dt.getMinutes());
  const s = pad(dt.getSeconds());
  return `${Y}-${M}-${D} ${h}:${m}:${s}`;
}

function formatNumber(value: number | string): string {
  if (typeof value === "number") {
    return value.toFixed(10).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  }
  return value;
}

export function buildSignalMessage(opts: {
  symbol: string;
  intent: Intent;
  orderType?: OrderType;
  positionSide?: PositionSide;
  autoTrade?: boolean;
  leverage?: number;
  marginUSDT?: number;
  quantity?: string;
  reduceOnly?: boolean;
  timestamp?: Date;
}): string {
  const {
    symbol,
    intent,
    orderType = "Market",
    positionSide = "LONG",
    autoTrade = false,
    leverage,
    marginUSDT,
    quantity,
    reduceOnly = false,
    timestamp
  } = opts;

  const { emoji, title } = emojiAndTitle(intent);

  const lines: string[] = [];
  lines.push(`${emoji} SIGNAL - ${title}`);
  lines.push("------------------------");
  lines.push(`Asset: ${symbol}`);

  if (typeof marginUSDT === "number") {
    lines.push(`Margin: ${formatNumber(marginUSDT)} USDT`);
  } else if (quantity) {
    lines.push(`Quantity: ${quantity}`);
  }

  if (typeof leverage === "number") {
    lines.push(`Leverage: ${formatNumber(leverage)}x`);
  }

  lines.push(`Auto-trade: ${autoTradeStr(autoTrade)}`);

  if (intent.includes("CLOSE")) {
    let exitType = orderType;
    if (reduceOnly) exitType += " (Reduce Only)";
    lines.push(`Exit Type: ${exitType}`);
  } else {
    lines.push(`Entry Type: ${orderType}`);
  }

  lines.push(`Position Side: ${positionSide}`);
  lines.push(`Timestamp: ${tsStr(timestamp)}`);

  return lines.join("\n");
}
