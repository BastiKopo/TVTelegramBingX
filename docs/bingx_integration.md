# BingX Integration Operations Guide

The BingX integration relies on authenticated REST and WebSocket connections and requires a few environment-level preconditions.

## Credentials and Environment Variables

* `BINGX_API_KEY` / `BINGX_API_SECRET` – API credentials generated from the BingX console.
* `BINGX_SUBACCOUNT_ID` – optional; populate when executing on behalf of a sub-account.
* `DEFAULT_MARGIN_MODE` / `DEFAULT_LEVERAGE` – defaults used when incoming signals omit the explicit values.

Store the credentials in the backend `.env` file or the deployment secrets store. The configuration loader in `backend/app/config.py` reads the same keys.

## Clock Synchronisation

BingX expects signed requests to include a millisecond timestamp closely aligned with server time. The `BingXRESTClient` exposes a `time_sync()` helper; call it on service start when deploying in environments without reliable NTP.

## WebSocket Consumers

Order and position updates are consumed via the BingX private WebSocket streams. Ensure outbound connectivity to `wss://open-api-ws.bingx.com` and keep-alive pings are permitted (the subscriber sends heartbeats every 15 seconds).

## Database Synchronisation

Order and position updates coming from BingX are reconciled with the local PostgreSQL (or SQLite in tests) database via the `BingXSyncService`. Schedule the periodic resync coroutine in your worker process (e.g., every 60 seconds) to recover from missed WebSocket events.
