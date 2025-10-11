export const BINGX_BASE = process.env.BINGX_BASE ?? "https://open-api.bingx.com";

// QUOTE (public)
export const PATH_QUOTE_PRICE = "/openApi/swap/v2/quote/price";
export const PATH_QUOTE_PREMIUM = "/openApi/swap/v2/quote/premiumIndex";
export const PATH_QUOTE_CONTRACTS = "/openApi/swap/v2/quote/contracts";

// TRADE (private, POST x-www-form-urlencoded)
export const PATH_ORDER = "/openApi/swap/v2/trade/order";
export const PATH_SET_LEVERAGE = "/openApi/swap/v2/trade/setLeverage";
export const PATH_SET_MARGIN = "/openApi/swap/v2/trade/setMarginMode";

// ACCOUNT (private, GET signed)
export const PATH_USER_BALANCE = "/openApi/swap/v2/user/balance";
export const PATH_USER_POSITIONS = "/openApi/swap/v2/user/positions";
export const PATH_USER_OPEN_ORDERS = "/openApi/swap/v2/user/openOrders";
