# 🎂 Anniversary Celebration

Intégration Home Assistant qui suit les anniversaires des personnes vivantes
et garde le souvenir des personnes décédées, avec une notification fiable
le jour J et une carte Lovelace qui se construit toute seule.

## Fonctionnalités

- Ajout/modification/suppression des personnes via l'interface (Paramètres →
  Appareils et services → Anniversary Celebration → Configurer) : prénom, nom,
  date de naissance, statut (vivant / décédé), heure de notification
  (optionnelle), appareil/service à notifier (optionnel).
- Un capteur par personne (`sensor.<prénom>_<nom>`) : nombre de jours avant le
  prochain anniversaire, âge actuel, âge au prochain anniversaire, date de
  naissance, statut, et si la notification du jour a déjà été envoyée.
- **Fiabilité des notifications** : pas de minuteur unique programmé des
  mois à l'avance (qui se perdrait à un redémarrage). L'intégration
  recalcule l'état de chaque personne **toutes les minutes** ; dès que le
  jour J et l'heure configurée sont atteints, la notification part une
  seule fois (mémorisée dans un stockage persistant, donc jamais répétée ni
  jamais oubliée même après un redémarrage de Home Assistant). Une
  notification persistante Home Assistant est en plus toujours créée,
  même si l'appareil choisi est indisponible.
- Les personnes décédées peuvent aussi être notifiées (message "en
  mémoire" différent de celui des vivants).
- Carte `anniversary-celebration-card` : se construit automatiquement à
  partir des personnes configurées (pas besoin de toucher le YAML du
  dashboard à chaque ajout), triée par proximité, avec un 🔔 à côté du nom
  si la notification du jour a déjà été envoyée.

## Carte — configuration

```yaml
type: custom:anniversary-celebration-card
title_alive: "🎂 Anniversaires"
title_deceased: "🕯️ Souvenirs"
show_deceased: true
max_items: 0   # 0 ou absent = toutes les personnes ; sinon nombre libre
```

## Installation (HACS)

1. HACS → Intégrations → ⋮ → Dépôts personnalisés → ajouter ce dépôt
   (catégorie Intégration).
2. Installer "Anniversary Celebration", redémarrer Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration →
   "Anniversary Celebration".
4. Configurer pour ajouter les premières personnes.
