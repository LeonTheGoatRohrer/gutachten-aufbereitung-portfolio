# Deployment: Gutachten-System auf DigitalOcean

Diese Anleitung beschreibt das Deployment des lokalen FastAPI-Prototyps
(`gutachten-system/`) auf einen DigitalOcean-Droplet fuer die **Testphase**.

> Wichtig: Hier wird **nicht** die oeffentliche Demo deployt. Die oeffentliche
> Gutachten-Demo bleibt statisch auf GitHub Pages unter
> `https://leonrohrer.at/gutachten/`. Dieser Droplet hostet die echte
> Arbeits-App mit Upload/Backend – passwortgeschuetzt und nicht oeffentlich
> verlinkt.

## Architektur

```
Browser  --HTTPS/HTTP-->  nginx (Port 80/443, Basic Auth, grosse Uploads)
                              |
                              v  Reverse Proxy
                          uvicorn (127.0.0.1:8000, systemd-Service)
                              |
                          FastAPI  app.main:app
                              |
                          projects/  (Daten auf der Droplet-Platte)
```

- Die App laeuft am **Root-Pfad** `/` (die Templates nutzen absolute
  `/static/...`-URLs, siehe Commit `9570caf`) – **kein** Subpfad.
- uvicorn bindet nur an `127.0.0.1` und ist ausschliesslich ueber nginx
  erreichbar.
- `projects/` (echte Kundendaten) ist **nicht** im Git und bleibt nur auf dem
  Server. Updates (`git pull`) loeschen diese Daten nicht.

## Eckdaten (vereinbart)

| Punkt        | Wert                                             |
|--------------|--------------------------------------------------|
| Anbieter     | DigitalOcean Droplet (kein App Platform)         |
| OS           | Ubuntu 24.04 LTS                                  |
| Region       | Frankfurt (FRA1)                                  |
| Groesse      | 2 GB RAM / 1 vCPU (~12 $/Monat)                  |
| Auth         | SSH Passwort **oder** SSH-Key                    |
| Web-Server   | nginx + uvicorn (systemd)                         |
| Zugangsschutz| HTTP Basic Auth (Testphase), HTTPS optional      |

---

## Phase 1 – Droplet erstellen (im DO-Webinterface)

1. **Create → Droplets**.
2. Image: **Ubuntu 24.04 (LTS) x64**.
3. Region: **Frankfurt**.
4. Plan: Basic → Regular → **2 GB / 1 vCPU**.
5. Authentifizierung: SSH-Key (empfohlen) oder Passwort.
6. Hostname z.B. `gutachten-app`.
7. **Create Droplet** → **oeffentliche IP notieren**.

Optional, aber empfohlen fuer HTTPS: Beim Domain-Anbieter von `leonrohrer.at`
einen **A-Record** anlegen, z.B. `app.leonrohrer.at` → `<DROPLET-IP>`.

---

## Phase 2 – Verbinden und Code holen

Aus PowerShell:

```powershell
ssh root@<DROPLET-IP>
```

Auf dem Droplet git installieren und Repo nach `/opt/gutachten` klonen:

```bash
apt-get update && apt-get install -y git
git clone https://github.com/LeonTheGoatRohrer/gutachten-aufbereitung.git /opt/gutachten
```

### Wenn das Repo privat ist

Die HTTPS-URL fragt dann nach Zugangsdaten. Zwei saubere Wege:

**A) Read-only Deploy-Key (empfohlen)**

```bash
ssh-keygen -t ed25519 -C "droplet-gutachten" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Den ausgegebenen Public Key auf GitHub eintragen:
Repo → **Settings → Deploy keys → Add deploy key** (Schreibrechte NICHT noetig).
Danach per SSH klonen:

```bash
git clone git@github.com:LeonTheGoatRohrer/gutachten-aufbereitung.git /opt/gutachten
```

**B) Personal Access Token (PAT)** mit `repo`-Leserecht in der HTTPS-URL:

```bash
git clone https://<PAT>@github.com/LeonTheGoatRohrer/gutachten-aufbereitung.git /opt/gutachten
```

---

## Phase 3 – Installieren (ein Skript)

```bash
# Argument 1: server_name -> Subdomain ODER IP ODER _ (= alles)
# Argument 2: optional Basic-Auth-Benutzername (Standard: gutachten)
bash /opt/gutachten/gutachten-system/deploy/setup.sh app.leonrohrer.at gutachten
```

Nur mit IP testen? Dann:

```bash
bash /opt/gutachten/gutachten-system/deploy/setup.sh _ gutachten
```

Das Skript:

1. installiert Python, nginx, apache2-utils,
2. legt den Service-Benutzer `gutachten` an,
3. erstellt das venv und installiert `requirements.txt`,
4. richtet den systemd-Service `gutachten.service` ein und startet ihn,
5. installiert die nginx-Config (mit deinem `server_name`),
6. fragt **interaktiv** nach dem Basic-Auth-Passwort,
7. testet und laedt nginx neu.

Danach erreichbar unter `http://<server_name-oder-IP>/` – Browser fragt nach
Benutzer/Passwort.

---

## Phase 4 – HTTPS aktivieren (nur mit Subdomain)

Erst sinnvoll, wenn `app.leonrohrer.at` per A-Record auf die IP zeigt:

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d app.leonrohrer.at
```

certbot ergaenzt automatisch den `listen 443`-Block und die Weiterleitung von
HTTP auf HTTPS.

> **Vor echten Kundendaten: HTTPS ist Pflicht.** Basic Auth ueber reines HTTP
> uebertraegt die Zugangsdaten nur base64-kodiert. Bis HTTPS aktiv ist, nur mit
> Test-/Dummy-Daten arbeiten (vgl. Datenschutzregeln in `PROJEKTZIELE.md`).

---

## Updates / Redeploy

Neuen Code ausrollen (Kundendaten bleiben erhalten):

```bash
bash /opt/gutachten/gutachten-system/deploy/update.sh
```

## Betrieb & Diagnose

```bash
systemctl status gutachten.service --no-pager   # laeuft der Dienst?
journalctl -u gutachten.service -f              # Live-Logs der App
systemctl restart gutachten.service             # Neustart
nginx -t && systemctl reload nginx              # nginx-Config testen/laden
```

Weiteren Basic-Auth-Benutzer anlegen:

```bash
htpasswd /etc/nginx/.htpasswd-gutachten <name>
```

## Bekannte Engpaesse (Diagnose aus der Planung)

- **Ordner-Upload langsam:** Engpass ist Browser-Upload + Leitung, nicht die
  Server-CPU. Der lokale „direkt-von-Platte"-Import entfaellt auf dem Remote-Server.
- **Bilder beim Zuordnen langsam:** Die App liefert Fotos in voller Aufloesung.
  Echte Loesung sind Thumbnails (spaeteres Feature, serverunabhaengig).
- **Upload bricht ab:** Pruefen, dass `client_max_body_size` in der nginx-Config
  hoch genug ist (aktuell `2g`).
