# TVTelegramBingX

## Konzeptübersicht

- **Signalquelle (TradingView)**: TradingView sendet Kauf-/Verkaufssignale via Webhook mit standardisiertem JSON-Payload (Symbol, Aktion, Confidence, Zeitstempel, Menge (`quantity`), Stop-Loss/Take-Profit sowie optional Margin-Modus und Hebel).
- **Server/Backend**:
  - Empfang und Verifizierung des Webhooks (Signaturprüfung, Rate Limits).
  - Event-Pipeline (Message-Queue) zur Entkopplung: `signals.raw` → `signals.validated` → `orders.executed`.
  - Orchestrierungsservice (z. B. FastAPI) zur Weiterleitung an Telegram und BingX.
  - State Management: persistiert Orders, PnL, Budgets in einer relationalen DB (z. B. PostgreSQL) + Redis für schnelle Statusabfragen.
  - Regelwerk/Risikomanagement (Max. Positionsgröße, Drawdown, Stopp-Strategien).
- **Telegram-Bot**:
  - Admin-Authentifizierung (z. B. via BotFather Token, Benutzer-Whitelist).
  - Menüstruktur (Inline-Keyboards) für die Modi: Auto-Trade, Manuell, Reports, Status, Help.
  - Push-Nachrichten zu neuen Signalen, ausgeführten Orders, Warnungen.
  - **Margin- und Hebelsteuerung**: Inline-Dialoge erlauben das Setzen von isolierter/Cross-Margin sowie die Anpassung des gewünschten Hebels pro Symbol oder globalem Profil. Änderungen werden serverseitig validiert (Max-Hebel, Risikoparameter) und sofort an BingX synchronisiert.
- **BingX-Anbindung**:
  - REST/WebSocket-Schnittstelle für Orderausführung, Kontostand, Positionsdaten.
  - API-Key-Speicher im Secret-Manager; Signatur- und Zeit-Synchronisierung.
  - Failover/Retry-Logik bei Netzwerkausfällen.
- **Monitoring & Sicherheit**:
  - Logging/Tracing (z. B. Prometheus + Grafana).
  - Alerts (Telegram/Email) bei Fehlern oder ungewöhnlichen PnL-Schwankungen.
  - Regelmäßige Backups, Secrets Rotation, Zugriffskontrolle.

## Signal- und Kommunikationsfluss

1. **TradingView → Server**
   - Webhook Endpoint `POST /webhook/tradingview`.
   - Validierung (Payload-Schema, Timestamp-Drift).
   - Normalisierung & Persistenz (`signals_raw` Tabelle).
2. **Server → Telegram**
   - Notification Service sendet Signalzusammenfassung an Bot.
   - Inline-Buttons für „Auto“ (direkte Order-Ausführung) und „Manuell“ (Bestätigung durch Nutzer).
   - Benutzerbefehle `/status`, `/report`, `/help`.
   - **Margin/Hebel-Anpassung**: Menüpunkt erlaubt Auswahl des Kontotyps (Spot, Futures), Margin-Modus (isolated/cross) und Hebel (numerische Eingabe mit Validierung). Änderungen werden persistent gespeichert und beim nächsten Signal angewendet.
3. **Server ↔ BingX**
   - Auto-Mode: sofortige Ordererstellung per API.
   - Manuell: Order erst nach Telegram-Bestätigung.
   - Statusabfragen: Kontostand, offene Trades, Historie.
   - Reports: tägliche/wöchentliche PnL-Zusammenfassung, exportierbar als CSV/PDF.
   - **Parameter-Sync**: Bei Margin- oder Hebeländerungen sendet der Server entsprechende API-Calls an BingX und bestätigt die erfolgreiche Aktualisierung im Telegram-Chat.
4. **Persistenz & Analytics**
   - Tabellen: `signals`, `orders`, `positions`, `balances`, `users`, `bot_sessions`.
   - PnL-Berechnung serverseitig, Reports optional per Scheduler (z. B. Celery Beat).

## Telegram-Funktionen im Detail

- **Auto Trade**: Toggle pro Nutzer/Konto; zeigt aktuellen Modus; Option zum globalen Stop.
- **Manuell**: Interaktive Bestätigungen, Möglichkeit Parameter (Menge, SL/TP) anzupassen.
- **Margin & Hebel**: Dialog führt Nutzer durch Auswahl von Symbol, Margin-Modus und Hebelwert; Validierung gegen Risikoregeln; Anzeige aktueller Parameter im Status-Menü.
- **Reports**: Aggregierte PnL-, Volumen-, Trefferquoten-Reports (tages-/wochenweise).
- **Status**: Budget, verfügbares Kapital, laufende Orders, Performance-Metriken, aktueller Margin/Hebel-Stand.
- **Help**: Dokumentation der Befehle, FAQ, Link zu Support.

## BingX-Integration

- Unterstützt Spot & Perpetuals je nach Strategie; Parameter pro Symbol konfigurierbar.
- Nutzung von Sub-Accounts für segregiertes Trading.
- WebSocket-Listener für Order- und Positionsupdates; synchronisiert mit Server-Datenbank.
- Fehlerbehandlung:
  - Idempotente Order-IDs zur Vermeidung doppelter Ausführungen.
  - Circuit Breaker bei API-Rate-Limit oder Timeout.
  - Automatische Re-Sync-Routine bei Inkonsistenzen.
  - **Margin/Hebel-Management**: Verwendung dedizierter BingX-Endpunkte zur Konfiguration von Margin-Modus und Hebel; Rollback bei fehlgeschlagenen Aktualisierungen.

## Betrieb & Governance

- **Deploy**: Containerisierte Services (Docker), orchestriert via Kubernetes oder Docker Compose.
- **CI/CD**: Tests für Signalverarbeitung, API-Mocks, End-to-End-Simulationen.
- **Sicherheitsmaßnahmen**: HTTPS, Secrets Management (Vault/Parameter Store), rollenbasierte Zugriffe.
- **Dokumentation**: OpenAPI-Spec für Backend, Bot-Kommandoreferenz, Runbooks für On-Call.

## Roadmap

### Phase 0 – Projektgrundlagen (Woche 1)
- Repository-Struktur aufsetzen (Backend, Bot, Infrastruktur, Docs).
- `.env`-Konfiguration anlegen und in Deployment-Skripte integrieren.
- Lokale Entwicklungsumgebung mit Docker Compose (DB, Redis) bereitstellen.
- Basis-Monitoring (Prometheus/Grafana-Stacks) als optionaler Service vorbereiten.

### Phase 1 – Signalaufnahme & Persistenz (Wochen 2–3)
- TradingView-Webhook (`POST /webhook/tradingview`) implementieren inkl. Authentifizierung & Schema-Validierung.
- Message-Queue (z. B. RabbitMQ/Kafka) aufsetzen; Topics `signals.raw`, `signals.validated`, `orders.executed`.
- Persistenzschicht (PostgreSQL) mit Tabellen `signals`, `orders`, `positions`, `balances`, `users`, `bot_sessions`.
- Unit- und Integrationstests für Signalvalidierung und Datenpersistenz implementieren.

### Phase 2 – Telegram-Bot & User-Interaktion (Wochen 4–5)
- Telegram-Bot mit Inline-Keyboards für Auto-Trade, Manuell, Reports, Status, Help.
- Margin-/Hebel-Menüs implementieren (Symbolwahl, Margin-Modus, Hebelvergabe, Validierung).
- User-Authentifizierung (Whitelist, Adminrollen) sowie Logging & Auditing der Benutzeraktionen.
- Report-Generator (PnL, Volumen, Trefferquote) als geplante Tasks (Celery Beat / Cron) mit Export (CSV/PDF).

### Phase 3 – BingX-Integration (Wochen 6–7)
- REST-Client (Spot & Perpetual) inkl. Signatur-/Timestamp-Handling.
- Auto-Trade Flow: Ordergenerierung, Retry/Circuit-Breaker, Idempotency Keys.
- Margin/Hebel-Synchronisierung: Nutzung BingX-Endpunkte, Rollback-Strategien bei Fehlern.
- WebSocket Listener für Order-/Positionsupdates und Synchronisation mit der lokalen Datenbank.

### Phase 4 – Stabilisierung & Betrieb (Wochen 8–9)
- End-to-End-Tests (Simulierte Signale → Telegram → BingX → Persistenz).
- Observability ausbauen (Tracing, Alerting-Regeln, Incident-Runbooks).
- Sicherheitsüberprüfung (Penetrationstest, Secrets-Rotation, Backup/Restore-Prozesse).
- Vorbereitung für Produktion: CI/CD-Pipeline, Container-Hardening, Dokumentationsabschluss.

## Environment-Konfiguration

Die Anwendung erwartet eine `.env`-Datei im Projektwurzelverzeichnis. Sie enthält alle relevanten Secrets und Konfigurationen für Telegram- und BingX-APIs. Ein Beispiel befindet sich in `.env.example`.

```bash
cp .env.example .env
# Werte anpassen
```

### Wichtige Variablen

- `TELEGRAM_BOT_TOKEN`: BotFather-Token für den Telegram-Bot.
- `TELEGRAM_ADMIN_IDS`: Kommagetrennte Liste autorisierter Benutzer-IDs.
- `TRADINGVIEW_WEBHOOK_TOKEN`: Gemeinsames Geheimnis für den Webhook-Aufruf von TradingView.
- `BINGX_API_KEY` / `BINGX_API_SECRET`: Zugangsdaten für die BingX-API.
- `BINGX_SUBACCOUNT_ID`: Optionaler Sub-Account für segregiertes Trading.
- `DEFAULT_MARGIN_MODE`: `isolated` oder `cross`, wird als Fallback genutzt.
- `DEFAULT_LEVERAGE`: Standardhebel bei noch nicht gesetzten Symbolparametern.
- `DATABASE_URL`: Verbindung zur Persistenzschicht (standardmäßig `postgresql+asyncpg://...`).
- `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_NAME` / `DATABASE_USER` / `DATABASE_PASSWORD`: Werden verwendet, um automatisch eine PostgreSQL-DSN zu generieren, falls `DATABASE_URL` nicht gesetzt ist.
- `TRADING_DEFAULT_USERNAME`: Standardkonto, dem eingehende Signale zugeordnet werden.
- `TRADING_DEFAULT_SESSION`: Name der Standardsitzung für automatisierte Orders.
- `BROKER_HOST` / `BROKER_PORT`: Adresse des Message-Brokers (z. B. RabbitMQ) für validierte Signale.
- `BROKER_USERNAME` / `BROKER_PASSWORD` / `BROKER_VHOST`: Zugangsdaten bzw. virtueller Host des Brokers.
- `BROKER_EXCHANGE`: Name der Exchange (Topic) für Signale.
- `BROKER_VALIDATED_ROUTING_KEY`: Routing-Key, unter dem validierte Signale veröffentlicht werden (Standard: `signals.validated`).

Die `.env` wird in Backend- und Bot-Services eingelesen. Secrets sind niemals im Repository zu speichern; für die Produktion sollte ein Secret-Manager (z. B. AWS Secrets Manager, Hashicorp Vault) genutzt werden.

### PostgreSQL-Betrieb ohne Docker

Für produktive Setups empfiehlt sich ein verwalteter PostgreSQL-Dienst (z. B. AWS RDS, Azure Database for PostgreSQL, Google Cloud SQL) oder eine dedizierte On-Premise-Installation. Wichtig ist, dass die Instanz SSL-Verbindungen erlaubt und regelmäßige Backups eingerichtet sind. Alternativ kann PostgreSQL manuell auf einem Linux-Host installiert werden (`apt install postgresql`), wobei Firewall-Regeln sowie Systemd-Units entsprechend anzupassen sind.

Nach der Bereitstellung wird die Verbindung über `DATABASE_URL` bzw. die Einzelparameter (`DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`) konfiguriert. Schemaänderungen erfolgen ausschließlich über Alembic-Migrationen. Nach einem Deployment sind daher folgende Schritte notwendig:

```bash
cd backend
alembic upgrade head
```

Die Alembic-Konfiguration kann auf denselben Verbindungsparametern aufsetzen. In CI/CD-Umgebungen sollte der Migrationsschritt Bestandteil der Release-Pipeline sein.

### Message-Broker-Anbindung (RabbitMQ-Beispiel)

Der FastAPI-Service veröffentlicht validierte Signale asynchron auf einen Message-Broker. Für eine produktive Umgebung empfiehlt sich ein verwalteter Dienst wie [CloudAMQP](https://www.cloudamqp.com/), AWS RabbitMQ oder Azure Service Bus (AMQP). Die wichtigsten Schritte:

1. Broker-Dienst bereitstellen (Managed RabbitMQ/Kafka ohne Docker-Setup vor Ort).
2. Zugriffsdaten kopieren und in der `.env` hinterlegen (`BROKER_*` Variablen, siehe oben).
3. Exchange vom Typ `topic` mit dem Namen aus `BROKER_EXCHANGE` anlegen (Standard: `signals`).
4. Downstream-Services (z. B. Order-Ausführung) abonnieren den Routing-Key `BROKER_VALIDATED_ROUTING_KEY` (Standard: `signals.validated`).

Ohne gesetzten `BROKER_HOST` startet der Service weiterhin mit einem In-Memory-Publisher – praktisch für lokale Tests, aber nicht für Produktionsbetrieb.

## Backend-Umsetzung – Phase 1 (Start)

Die ersten Code-Artefakte für Phase 1 befinden sich im Verzeichnis `backend/` und bestehen aus folgenden Komponenten:

- **FastAPI-Service** (`backend/app/main.py`): Endpunkte `/health`, `/webhook/tradingview` und `/signals`.
- **Konfigurations-Handling** (`backend/app/config.py`): Lädt `.env`-Variablen mittels `pydantic-settings`.
- **Persistenzschicht** (`backend/app/db.py`, `backend/app/repositories`): SQLModel-Modelle und Repositorys für Signale, Orders, Positionen, Balances, Nutzer und Bot-Sitzungen (PostgreSQL via asyncpg).
- **Domain-Service & Queue** (`backend/app/services`): Persistiert Signale und publiziert sie per Broker-Publisher (`aio-pika`) an `signals.validated` (in Tests weiterhin In-Memory).
- **Tests** (`backend/tests`): Validieren Token-Schutz, Persistenz und Queue-Veröffentlichung.

### Lokales Setup

```bash
cp .env.example .env  # einmalig anlegen und Werte ausfüllen
./run.sh
```

Das Skript `run.sh` erledigt alle notwendigen Schritte:

1. Prüft, ob eine `.env` existiert, und erinnert ansonsten ans Kopieren der Vorlage.
2. Legt bei Bedarf ein virtuelles Environment unter `backend/.venv` an.
3. Installiert bzw. aktualisiert alle Python-Abhängigkeiten via `pip install -e ".[dev]"`.
4. Startet den FastAPI-Service mit Uvicorn (`--reload`) auf Port `8000` (konfigurierbar über `PORT`).

Der Service lauscht anschließend auf `http://127.0.0.1:8000`. Der TradingView-Webhook erwartet einen Header `X-TRADINGVIEW-TOKEN`, der mit `TRADINGVIEW_WEBHOOK_TOKEN` übereinstimmen muss.

### Tests ausführen

```bash
cd backend
pytest
```

Die Tests nutzen eine temporäre PostgreSQL-Instanz (bereitgestellt durch `pytest-postgresql`) und prüfen sowohl die Zurückweisung ungültiger Tokens als auch die erfolgreiche Speicherung und Weiterleitung von Signalen samt Persistenz der neuen Trading-Tabellen.

## Testing

## Setup-Checkliste

Eine ausführliche Aufgaben- und Installationsliste findest du in [`docs/installation_checklist.md`](docs/installation_checklist.md). Die Checkliste deckt benötigte Konten, Infrastruktur, lokale Entwicklungsumgebung sowie Betriebsthemen ab und kann als pragmatische To-do-Liste genutzt werden.

- ⚠️ Keine Tests ausgeführt (Konzeptdokumentation).
