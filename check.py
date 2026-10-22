#!/usr/bin/env python3
"""
BaseCheck Cloud Monitor — Surveillance Dynamique & Chien de Garde
=================================================================
Fuseau horaire : GMT+1 fixe.
Cadences :
  - 05h00 à 09h00 GMT+1 : Vérification toutes les 15 minutes (Allumage base)
  - 17h00 à 00h00 GMT+1 : Vérification toutes les 15 minutes (Extinction base)
  - Reste de la journée & nuit : Vérification toutes les 30 minutes

Chien de garde (Watchdog) :
  - À chaque check, vérification à T+2 min de l'enregistrement.
  - Si échec ou absence, relance immédiate du check.
  - Le script tourne en boucle précise pendant ~48 minutes par session
    pour éliminer totalement les retards de file d'attente de GitHub Actions.
"""

import socket
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

# ── Configuration ─────────────────────────────────────────────
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

# Fuseau horaire : GMT+1 fixe
TZ_GMT1 = timezone(timedelta(hours=1))
# ──────────────────────────────────────────────────────────────


def get_current_cadence(dt_utc: datetime):
    """
    Retourne la cadence cible en minutes selon l'heure locale (GMT+1) :
      - 05h00 à 08h59 : 15 min (Allumage matin)
      - 17h00 à 23h59 : 15 min (Extinction soir)
      - 09h00 à 16h59 et 00h00 à 04h59 : 30 min (Heures normales)
    """
    dt_local = dt_utc.astimezone(TZ_GMT1)
    hour = dt_local.hour
    if (5 <= hour < 9) or (17 <= hour < 24):
        return 15, "Période critique 15 min (05h-09h / 17h-minuit GMT+1)"
    else:
        return 30, "Période normale 30 min (09h-17h / minuit-05h GMT+1)"


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


def save_to_supabase(result: dict) -> bool:
    """Enregistre le statut dans la table Supabase base_checks."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[BaseCheck] Erreur: Identifiants Supabase manquants.")
        return False

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/base_checks"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = json.dumps({
        "status": result["status"],
        "created_at": result["timestamp"]
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            inserted_id = data[0]["id"] if data else None
            result["inserted_id"] = inserted_id
            print(f"[BaseCheck] Enregistré dans Supabase (ID: {inserted_id}, Status: {resp.status})")
            return True
    except Exception as e:
        print(f"[BaseCheck] Erreur enregistrement Supabase: {e}")
        return False


def get_last_check_from_supabase() -> dict:
    """Récupère le dernier check enregistré dans Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/base_checks?select=id,status,created_at&order=created_at.desc&limit=1"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                row = data[0]
                ts = row["created_at"].strip()
                if ts.endswith("+00"):
                    ts = ts[:-3] + "+00:00"
                row["dt_utc"] = datetime.fromisoformat(ts)
                return row
    except Exception as e:
        print(f"[BaseCheck] Erreur lecture Supabase: {e}")
    return None


def execute_cycle():
    """
    Exécute un cycle complet :
      1. Test physique de la base
      2. Enregistrement dans Supabase
      3. Contrôle chien de garde à T+2 min
    """
    now_utc = datetime.now(timezone.utc)
    cadence, desc = get_current_cadence(now_utc)
    loc_str = now_utc.astimezone(TZ_GMT1).strftime("%H:%M:%S GMT+1")
    print(f"\n────────────────────────────────────────────────────────")
    print(f"[Cycle] Heure locale : {loc_str} | Cadence requise : {cadence} min ({desc})")

    # 1. Vérification de la base
    result = check_base()
    print(f"[Cycle] Résultat : {result['status']} @ {result['timestamp']}")

    # 2. Sauvegarde Supabase
    success = save_to_supabase(result)

    # 3. Chien de garde après 2 minutes (120 secondes)
    print(f"[Chien de Garde] Attente de 2 minutes pour vérification...")
    time.sleep(120)

    # Vérification dans Supabase que le check a bien été pris en compte
    latest = get_last_check_from_supabase()
    check_ok = False
    if latest and "inserted_id" in result and result["inserted_id"]:
        check_ok = (latest["id"] >= result["inserted_id"])
    elif latest and success:
        diff_s = (datetime.now(timezone.utc) - latest["dt_utc"]).total_seconds()
        check_ok = (diff_s < 200)

    if not check_ok:
        print("[Chien de Garde] ⚠️ ANOMALIE: Le check n'a pas été confirmé ! Relance immédiate...")
        retry_res = check_base()
        save_to_supabase(retry_res)
    else:
        print("[Chien de Garde] ✅ Contrôle validé avec succès à T+2 min.")

    return cadence


def main():
    print(f"=== BaseCheck Monitor — Démarrage de la session ===")
    session_start = time.time()
    max_session_seconds = 48 * 60  # La session tourne pendant ~48 minutes max

    while (time.time() - session_start) < max_session_seconds:
        # Vérifier si un check récent a déjà été fait (ex: par test manuel ou runner précédent)
        now_utc = datetime.now(timezone.utc)
        cadence, desc = get_current_cadence(now_utc)
        last_record = get_last_check_from_supabase()

        if last_record:
            elapsed_min = (now_utc - last_record["dt_utc"]).total_seconds() / 60
            # Seuil de déclenchement : si le dernier check a moins de 11 min (en période 15) ou 22 min (en période 30)
            threshold = 11 if cadence == 15 else 22
            if elapsed_min < threshold:
                wait_sec = int((threshold - elapsed_min) * 60)
                print(f"[BaseCheck] Dernier check il y a {elapsed_min:.1f} min. Attente de {wait_sec}s avant le prochain test...")
                time.sleep(min(wait_sec, 300))
                continue

        # Exécuter le cycle (test + sauvegarde + chien de garde 2 min)
        cadence_used = execute_cycle()

        # Attendre le temps restant (cadence - 2 min déjà écoulées dans le chien de garde)
        remaining_wait_sec = max(10, (cadence_used - 2) * 60)
        print(f"[BaseCheck] Prochain check dans {remaining_wait_sec // 60} min...")

        # Ne pas attendre au-delà de la fin de session
        time_left_session = max_session_seconds - (time.time() - session_start)
        if time_left_session <= remaining_wait_sec:
            print("[BaseCheck] Fin de session normale (relais au prochain runner).")
            break

        time.sleep(remaining_wait_sec)

    print("=== BaseCheck Monitor — Session terminée proprement ===")


if __name__ == "__main__":
    main()
