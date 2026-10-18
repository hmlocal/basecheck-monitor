#!/usr/bin/env python3
"""
BaseCheck Cloud Monitor
=======================
Vérifie toutes les 30 minutes si la base NTRIP est en ligne.
Envoie le résultat directement dans la base de données privée Supabase.
Aucun fichier de journal n'est écrit ou stocké sur GitHub.

Les paramètres sensibles sont stockés dans les GitHub Secrets :
- NTRIP_HOST
- NTRIP_PORT
- NTRIP_MOUNTPOINT
- SUPABASE_URL
- SUPABASE_KEY
"""

import socket
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# ── Configuration — lue depuis les secrets GitHub ──────────────
HOST         = os.environ.get("NTRIP_HOST")
PORT_STR     = os.environ.get("NTRIP_PORT", "2101")
MOUNTPOINT   = os.environ.get("NTRIP_MOUNTPOINT")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not HOST or not MOUNTPOINT:
    print("ERREUR : Les variables NTRIP_HOST et NTRIP_MOUNTPOINT doivent être définies.")
    sys.exit(1)

try:
    PORT = int(PORT_STR)
except ValueError:
    PORT = 2101

TIMEOUT = 10  # secondes
# ──────────────────────────────────────────────────────────────


def check_base() -> dict:
    """
    Vérifie l'état de la base NTRIP.
    Retours possibles :
      - "ONLINE"        : Base active
      - "BASE_OFFLINE"  : Serveur joignable, base éteinte
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
                if len(buffer) > 65536:
                    break

        if found:
            return {"status": "ONLINE", "timestamp": now_utc}
        elif received_any:
            return {"status": "BASE_OFFLINE", "timestamp": now_utc}
        else:
            return {"status": "NO_INTERNET", "timestamp": now_utc}

    except Exception as e:
        return {"status": "NO_INTERNET", "timestamp": now_utc, "error": str(e)}


def save_to_supabase(result: dict):
    """Enregistre le statut directement dans la table Supabase base_checks."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[BaseCheck] Attention: SUPABASE_URL ou SUPABASE_KEY non défini.")
        return

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/base_checks"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    payload = json.dumps({
        "status": result["status"],
        "created_at": result["timestamp"]
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[BaseCheck] Enregistré avec succès dans Supabase (Code: {resp.status})")
    except Exception as e:
        print(f"[BaseCheck] Erreur enregistrement Supabase: {e}")


def main():
    print(f"[BaseCheck] Vérification de la base NTRIP...")
    result = check_base()
    print(f"[BaseCheck] Résultat : {result['status']} @ {result['timestamp']}")

    save_to_supabase(result)


if __name__ == "__main__":
    main()
