# Setup- und Installations-Checkliste

Diese Liste fasst alle benötigten Konten, Tools und Installationsschritte für das TradingView/Telegram/BingX-Projekt zusammen. Sie ist als praktische "Bauchliste" konzipiert, damit schnell sichtbar wird, was erledigt wurde und welche Schritte noch offen sind.

## 1. Zugangsdaten & Konten

- [ ] **TradingView**
  - [ ] Pro/Enterprise-Plan mit Webhook-Unterstützung.
  - [ ] Strategie/Indicator vorbereiten, der Signale via Webhook versendet.
- [ ] **Telegram**
  - [ ] Telegram-Account für den Betreiber.
  - [ ] Bot via [@BotFather](https://t.me/botfather) anlegen (`/newbot`).
  - [ ] Bot-Token notieren und in `.env` als `TELEGRAM_BOT_TOKEN` hinterlegen.
  - [ ] Admin-IDs ermitteln (`/getid`-Bots oder eigene Nachrichten-ID) und als `TELEGRAM_ADMIN_IDS` hinterlegen.
- [ ] **BingX**
  - [ ] Konto mit Futures/Spot-Trading-Rechten.
  - [ ] API-Schlüssel mit Handelsrechten erstellen (IP-Whitelist optional).
  - [ ] API-Key & Secret sicher speichern (`BINGX_API_KEY`, `BINGX_API_SECRET`, optional `BINGX_SUBACCOUNT_ID`).

## 2. Infrastruktur & Sicherheit

- [ ] **Server/Hosting**
  - [ ] VPS oder Cloud-Instanz (2 vCPUs, 4 GB RAM als Ausgangspunkt).
  - [ ] Betriebssystem: Ubuntu 22.04 LTS (oder äquivalent).
  - [ ] SSH-Zugang härten (Key-basiert, Firewall-Regeln einrichten).
- [ ] **Domain & TLS**
  - [ ] Domain registrieren (optional, aber empfohlen für HTTPS).
  - [ ] Reverse Proxy (Nginx/Caddy) für TLS-Termination.
  - [ ] Zertifikat via Let's Encrypt (z. B. `certbot`) oder Managed TLS.
- [ ] **Secrets Management**
  - [ ] `.env` Datei nur lokal speichern, niemals committen.
  - [ ] Für Produktion: Secret-Manager (AWS Secrets Manager, Hashicorp Vault o. Ä.) auswählen.

## 3. Lokale Entwicklungsumgebung

- [ ] **Systempakete installieren**
  ```bash
  sudo apt update
  sudo apt install -y python3 python3-venv python3-pip git
  ```
- [ ] **Repository klonen**
  ```bash
  git clone git@github.com:<dein-account>/TVTelegramBingX.git
  cd TVTelegramBingX
  ```
- [ ] **Python-Venv aufsetzen & Abhängigkeiten installieren**
  ```bash
  cd backend
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e .[dev]
  ```
- [ ] **Beispiel-Umgebungsdatei kopieren & anpassen**
  ```bash
  cp ../.env.example ../.env
  # Variablen im Editor anpassen
  ```

## 4. Datenbanken & Queues

- [ ] **PostgreSQL (Produktion)**
  ```bash
  sudo apt install -y postgresql postgresql-contrib
  sudo -u postgres createuser tvtbot --pwprompt
  sudo -u postgres createdb tvtbot_db -O tvtbot
  ```
  - Verbindung in `.env` als `DATABASE_URL=postgresql+psycopg://tvtbot:<passwort>@localhost:5432/tvtbot_db` hinterlegen.
- [ ] **Redis (für Caching/Queues, optional)**
  ```bash
  sudo apt install -y redis-server
  sudo systemctl enable --now redis-server
  ```
- [ ] **Lokale Entwicklung (SQLite + In-Memory Queue)**
  - Keine zusätzliche Installation notwendig; Konfiguration bereits in der FastAPI-App enthalten.

## 5. TradingView Webhook-Konfiguration

- [ ] Endpoint in TradingView einstellen: `https://<deine-domain>/webhook/tradingview`.
- [ ] Header `X-TRADINGVIEW-TOKEN` auf Wert `TRADINGVIEW_WEBHOOK_TOKEN` aus `.env` setzen.
- [ ] Payload-Template (Beispiel):
  ```json
  {
    "symbol": "BTCUSDT",
    "action": "buy",
    "timestamp": "2024-05-01T12:34:56Z",
    "quantity": 0.01,
    "confidence": 0.9,
    "stop_loss": 26000,
    "take_profit": 28000,
    "leverage": 5,
    "margin_mode": "isolated"
  }
  ```

## 6. Telegram-Bot Konfiguration

- [ ] Bot-Webhook oder Long Polling auswählen (Entwicklung: Polling, Produktion: Webhook).
- [ ] Menüstruktur definieren (Auto Trade, Manuell, Reports, Status, Help, Margin/Hebel).
- [ ] Permissions auf Admin-IDs beschränken.
- [ ] Logging/Monitoring einrichten (z. B. Sentry, Prometheus-Exporter).

## 7. BingX-Integration vorbereiten

- [ ] Offizielle API-Dokumentation studieren (REST & WebSocket).
- [ ] Zeitsynchronisation prüfen (Server-Zeit mit NTP synchronisieren).
- [ ] Netzwerkrichtlinien: IP-Whitelist in BingX-Konsole setzen.
- [ ] Test-Requests mit `curl` oder `httpie` ausführen, um API-Key zu verifizieren.

## 8. Deployment-Grundlagen

- [ ] Docker & Docker Compose installieren (optional, empfohlen für Produktion)
  ```bash
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  sudo usermod -aG docker $USER
  # Re-login erforderlich, damit docker ohne sudo funktioniert
  sudo apt install -y docker-compose-plugin
  ```
- [ ] CI/CD-Pipeline planen (GitHub Actions, GitLab CI, etc.).
- [ ] Monitoring-Stack vorbereiten (Prometheus, Grafana, Alertmanager).

## 9. Tests & Qualitätssicherung

- [ ] Unit-Tests lokal ausführen (`pytest`).
- [ ] Optional: API-Tests mit `httpx`/`pytest-asyncio` (benötigt Internetzugang für Installation der Pakete).
- [ ] Linting & Formatting (z. B. `ruff`, `black`, `isort`) einführen.

## 10. Betrieb & Wartung

- [ ] Backup-Strategie für Datenbank & Konfigurationsdateien festlegen.
- [ ] Incident-Runbooks erstellen (z. B. „API Down“, „Order Sync Error“).
- [ ] Regelmäßige Überprüfung der Margin-/Hebel-Defaults in Telegram.
- [ ] Sicherheitsupdates des Servers automatisieren (`unattended-upgrades`).

> **Hinweis:** Diese Checkliste sollte fortlaufend gepflegt werden. Ergänze bei Bedarf weitere Punkte (z. B. Frontend, zusätzliche Bots) und hake erledigte Aufgaben ab.
