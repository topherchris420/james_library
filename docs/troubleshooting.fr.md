# Depannage (FR)

Entree FR de depannage:

- Version canonique: [`troubleshooting.md`](troubleshooting.md)
- Guide detaille: [`troubleshooting.md`](troubleshooting.md)

## Jugement typé facultatif

La commande `python rain_lab.py judge --evidence cycle.json` évalue un dossier
de preuves sélectionnées. Le [guide du jugement typé](typed-judgment.md)
(en anglais) décrit le schéma JSON et les seuils de décision exacts.

- `INVALID EVIDENCE OR CONFIGURATION` (code de sortie 2) : vérifier le schéma
  `rain-judgment-cycle/v1`, les champs requis, les types, les clés JSON en double
  et la limite de 128 Kio. Retirer les champs inconnus et les secrets du dossier.
  `RAIN_JUDGMENT_PROVIDER` doit valoir `off` ou `typesafe`.
- `DISABLED` : `off` est la valeur par défaut. Pour activer Jev volontairement,
  définir `RAIN_JUDGMENT_PROVIDER=typesafe` et `TYPESAFE_API_KEY` dans
  l'environnement local. Ne pas placer la clé dans un dossier de preuves,
  un journal ou un ticket. `TYPESAFE_MODEL` est facultatif (`jev-latest` par défaut).
- `NOT_RUN` (affiché `NOT RUN`) avec `peer_score_below_threshold` : le score
  de critique est inférieur à 8 ; réviser la proposition. Le fournisseur
  n'a pas été appelé.
- `UNAVAILABLE` avec `provider_not_configured` ou `provider_authentication_error` :
  vérifier la présence et la validité de `TYPESAFE_API_KEY` dans l'environnement
  du processus. Avec `provider_timeout` ou `provider_transport_error`, vérifier
  la connexion et la disponibilité du service. Avec `provider_rate_limited`,
  attendre avant de relancer manuellement. Aucun nouvel essai ni recours à un
  autre modèle n'est automatique ; un échec ne permet jamais la promotion.
- `REVISE` : corriger les preuves, les contradictions, la portée de la
  proposition ou une validation locale échouée. `HUMAN_REVIEW` : faire examiner
  explicitement l'incertitude ; une validation absente ou en erreur, ou un état
  tronqué, impose aussi cet examen. Consulter la politique du guide pour les
  seuils. Le code de sortie 1 signifie que la découverte n'a pas été promue.
- `RECORDED JUDGMENT INVALID` (code de sortie 2) lors de `judge --replay` :
  vérifier que le fichier est un artefact de session intact. Une empreinte
  d'état ou d'enveloppe incohérente est rejetée ; récupérer l'original plutôt
  que recalculer l'empreinte pour masquer une modification. La relecture
  n'appelle aucun fournisseur.

La relecture des cas de référence désactive toujours le jugement dans ses
processus enfants et retire les identifiants TypeSafe. `--live-judgment` est
refusé : utiliser explicitement `judge --evidence` pour une nouvelle évaluation.
Un résultat `PASS` est une décision de routage bornée, pas une preuve scientifique.

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
