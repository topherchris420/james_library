# Référence de configuration (FR)

Schéma de configuration canonique:

- [`../src/config/schema.rs`](../src/config/schema.rs)

Chargement/fusion de config:

- [`../src/config/mod.rs`](../src/config/mod.rs)

Clés plugin récentes à connaître :

- `[plugins].marketplace_enabled` (désactivé par défaut, requis pour les sources HTTP(S))
- `[plugins].allowed_permissions` (liste d’autorisations acceptées à l’installation)

## Sections du runtime autonome (ajoutées 2026-06)

Toutes désactivées par défaut ; les omettre conserve le comportement
antérieur.

- `[autonomous_runtime]` — exécute les tâches de fond (à commencer par le
  heartbeat) via le pulse driver de `src/autonomy/` ; inclut
  `[autonomous_runtime.vitals]` (seuils de stagnation/impasse du moniteur
  de vitaux). Nommée ainsi pour éviter la collision avec la section de
  sécurité `[autonomy]`.
- `[senses]` — bus sensoriel priorisé pour l'entrée des canaux (capacités
  des files, crédit anti-famine, tampon ambiant, fenêtre de coalescence).
- `[hooks.builtin].episodic_events` — ajoute une ligne JSONL par appel
  d'outil dans `episodic_memory/episodic_events.jsonl` (nom d'outil,
  résultat, durée uniquement ; jamais d'arguments ni de sorties).

Conception : [`autonomous-runtime-design.md`](autonomous-runtime-design.md).

## Environnement du jugement typé

- `RAIN_JUDGMENT_PROVIDER=off|typesafe` (défaut : `off`)
- `TYPESAFE_API_KEY` (requis uniquement avec TypeSafe)
- `TYPESAFE_MODEL` (défaut : `jev-latest`)

Un échec du fournisseur produit `UNAVAILABLE`, sans nouvelle tentative ni
fournisseur de secours. Voir [`typed-judgment.md`](typed-judgment.md).

## Routage optionnel des décisions bornées

`python rain_lab.py decide --request examples/bounded-decision.json` produit une
proposition, sans exécuter d'action. `decide --replay ARTIFACT` relit hors ligne.
`RAIN_DECISION_MODE=off|laya|jev|cascade` vaut `off` par défaut.
`RAIN_METACOGNITIVE_CONTROL=false` conserve la conversation existante.
Laya nécessite `RAIN_LAYA_CHECKPOINT`; les propositions calibrées nécessitent
`RAIN_DECISION_CALIBRATION`. Un modèle ou une calibration indisponible renvoie
la décision à R.A.I.N. L'accès distant nécessite un consentement explicite;
la conversation exige aussi `RAIN_DECISION_REMOTE_ALLOWED=true`.
Les erreurs de configuration sont signalées. Voir [décisions bornées](bounded-decisions.md)
pour la configuration complète, les diagnostics et le retour arrière.
La politique de promotion de `judge` reste inchangée.
