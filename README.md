# BaseCheck Cloud Monitor 🛰️

Surveillance automatique 24h/24 — 7j/7 de la base NTRIP `MP12571`.

## Comment ça marche

1. **GitHub Actions** vérifie la base toutes les 10 minutes → écrit dans `data/log.json`
2. **GitHub Pages** héberge `index.html` qui lit ce fichier → tableau de bord accessible depuis n'importe où

## Tableau de bord

🔗 **`https://<votre-username>.github.io/basecheck-monitor/`**

## Ce qu'affiche le tableau de bord

- Statut actuel (En ligne / Base hors-ligne / Pas d'Internet)
- Timeline de disponibilité sur les 24 dernières heures
- Statistiques sur 7 jours : uptime %, nombre de coupures, durée moyenne
- Historique journalier avec heures d'allumage et d'extinction

## Fuseau horaire

Les données sont stockées en UTC et **converties automatiquement** dans votre fuseau local à l'affichage.
