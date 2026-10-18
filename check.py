#!/usr/bin/env python3
"""
BaseCheck Cloud Monitor
=======================
Vérifie toutes les 10 minutes si la base NTRIP est en ligne.
Loggue chaque vérification dans data/log.json.
Le fichier JSON est ensuite lu par index.html (GitHub Pages).

Les paramètres sensibles (HOST, PORT, MOUNTPOINT) sont lus depuis
des variables d'environnement définies comme GitHub Secrets.
Rien de sensible n'apparaît dans le code source public.
"""

import socket
import json
import os
import sys
from datetime import datetime, timezone

# ── Configuration — lue depuis les secrets GitHub ──────────────
HOST       = os.environ.get("NTRIP_HOST")
PORT_STR   = os.environ.get("NTRIP_PORT", "2101")
MOUNTPOINT = os.environ.get("NTRIP_MOUNTPOINT")

if not HOST or not MOUNTPOINT:
    print("ERREUR : Les variables NTRIP_HOST et NTRIP_MOUNTPOINT doivent être définies.")
    print("         Ajoutez-les comme Secrets dans : Settings → Secrets → Actions")
    sys.exit(1)

try:
    PORT = int(PORT_STR)
except ValueError:
    PORT = 2101

TIMEOUT     = 10        # secondes
LOG_FILE    = "data/log.json"
MAX_ENTRIES = 4500      # ~94 jours à 30 min = couverture 3 mois complets
# ──────────────────────────────────────────────────────────────


def check_base() -> dict:
    """
    Vérifie l'état de la base NTRIP.
    Retourne un dict avec status, timestamp, et message.

    Retours possibles :
      - "ONLINE"        : Le point de montage est trouvé dans la sourcetable
      - "BASE_OFFLINE"  : Le serveur répond mais la base n'est pas dans la table
      - "NO_INTERNET"   : Impossible de joindre le serveur
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        request = (
            f"GET / HTTP/1.0\r\n"
            f"Host: {HOST}:{PORT}\r\n"
            f"Ntrip-Version: Ntrip/2.0\r\n"
            f"User-Agent: NTRIP PythonMonitor/1.0\r\n"
            f"\r\n"
        )

        with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as sock:
            sock.sendall(request.encode())
            received_any = False
            found = False
            buffer = b""

            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                received_any = True
                buffer += chunk
                if MOUNTPOINT.encode() in buffer:
                    found = True
                    break
                if len(buffer) > 65536:  # 64 KB suffisent
                    break

        if found:
            return {"status": "ONLINE", "timestamp": now_utc}
        elif received_any:
            return {"status": "BASE_OFFLINE", "timestamp": now_utc}
        else:
            return {"status": "NO_INTERNET", "timestamp": now_utc}

    except Exception as e:
        return {"status": "NO_INTERNET", "timestamp": now_utc, "error": str(e)}


def load_log() -> list:
    """Charge le journal existant depuis log.json."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_log(entries: list):
    """Sauvegarde les entrées dans log.json (dernières MAX_ENTRIES seulement)."""
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    os.makedirs("data", exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, separators=(",", ":"))


def main():
    print(f"[BaseCheck] Vérification de {HOST}:{PORT}/{MOUNTPOINT}...")

    result = check_base()
    print(f"[BaseCheck] Résultat : {result['status']} @ {result['timestamp']}")

    entries = load_log()
    entries.append(result)
    save_log(entries)

    print(f"[BaseCheck] Journal mis à jour ({len(entries)} entrées).")


if __name__ == "__main__":
    main()
