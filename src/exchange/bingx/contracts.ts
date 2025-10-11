function pow10(n: number): string {
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(`pow10 expects a non-negative finite number, received ${n}`);
  }
  if (n === 0) {
    return "1";
  }
  const value = 1 / Math.pow(10, n);
  return value.toString();
}

function toDecimalString(input: unknown): string | undefined {
  if (input === undefined || input === null) {
    return undefined;
  }
  if (typeof input === "number") {
    if (!Number.isFinite(input)) {
      return undefined;
    }
    return input.toString();
  }
  if (typeof input === "string") {
    const trimmed = input.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }
  if (typeof input === "bigint") {
    return input.toString();
  }
  return undefined;
}

function toPositiveDecimalString(input: unknown): string | undefined {
  const token = toDecimalString(input);
  if (!token) {
    return undefined;
  }
  const value = Number(token);
  if (!Number.isFinite(value) || value <= 0) {
    return undefined;
  }
  return value.toString();
}

export interface NormalizedContractFilters {
  stepSize: string;
  minQty: string;
  tickSize: string;
  pricePrecision?: number;
  quantityPrecision?: number;
}

export function normalizeContractFilters(raw: Record<string, unknown>): NormalizedContractFilters {
  let stepSize = toPositiveDecimalString(raw.stepSize);
  let quantityPrecision: number | undefined;

  if (!stepSize) {
    if (raw.quantityPrecision !== undefined) {
      const qp = Number(raw.quantityPrecision);
      if (Number.isFinite(qp) && qp >= 0) {
        quantityPrecision = Math.trunc(qp);
        stepSize = pow10(quantityPrecision);
      }
    }
    if (!stepSize && raw.size !== undefined) {
      stepSize = toPositiveDecimalString(raw.size);
    }
  } else if (raw.quantityPrecision !== undefined) {
    const qp = Number(raw.quantityPrecision);
    if (Number.isFinite(qp) && qp >= 0) {
      quantityPrecision = Math.trunc(qp);
    }
  }

  if (!stepSize) {
    const symbol = typeof raw.symbol === "string" ? raw.symbol : "<unknown>";
    throw new Error(`missing stepSize/quantityPrecision/size in ${symbol}`);
  }

  if (quantityPrecision === undefined && raw.quantityPrecision !== undefined) {
    const qp = Number(raw.quantityPrecision);
    if (Number.isFinite(qp) && qp >= 0) {
      quantityPrecision = Math.trunc(qp);
    }
  }

  let minQty = toPositiveDecimalString(raw.tradeMinQuantity) ?? stepSize;

  let tickSize = toPositiveDecimalString(raw.tickSize);
  let pricePrecision: number | undefined;
  if (!tickSize && raw.pricePrecision !== undefined) {
    const pp = Number(raw.pricePrecision);
    if (Number.isFinite(pp) && pp >= 0) {
      pricePrecision = Math.trunc(pp);
      tickSize = pow10(pricePrecision);
    }
  } else if (raw.pricePrecision !== undefined) {
    const pp = Number(raw.pricePrecision);
    if (Number.isFinite(pp) && pp >= 0) {
      pricePrecision = Math.trunc(pp);
    }
  }

  if (!tickSize) {
    tickSize = "0.01";
  }

  return {
    stepSize: stepSize,
    minQty: minQty,
    tickSize: tickSize,
    pricePrecision,
    quantityPrecision,
  };
}

export default normalizeContractFilters;
