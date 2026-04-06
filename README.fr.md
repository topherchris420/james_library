# Point d’entrée de la documentation R.A.I.N. Lab (FR)

<p align="center">
  <a href="https://github.com/topherchris420/james_library/actions/workflows/ci.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/tests.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/tests.yml/badge.svg?branch=main" alt="Tests" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml/badge.svg?branch=main" alt="Docs" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml/badge.svg?branch=main" alt="Security Audit" /></a>
</p>

> Cette page est le point d’entrée français, aligné sur le README principal et l’architecture docs.

## Navigation

- README principal : [`README.md`](README.md)
- Hub docs (FR) : [`docs/README.fr.md`](docs/README.fr.md)
- Table des matières unifiée : [`docs/SUMMARY.md`](docs/SUMMARY.md)

## Carte rapide d'identité du projet

- **R.A.I.N. Lab** : l'expérience produit côté utilisateur final
- **James Library** : la couche Python de recherche/workflows
- **R.A.I.N.** : la couche runtime Rust (crate `R.A.I.N.`)

Flux d'exécution : `Utilisateur -> interface R.A.I.N. Lab -> runtime R.A.I.N. -> workflows de recherche James Library -> API modèle/provider`

## Toutes les capacités de James

James n'est pas un simple chat multi-agents — c'est un véritable système d'exploitation pour la recherche : 10+ fournisseurs de modèles, 25+ plateformes de messagerie, 60+ outils intégrés, contrôle matériel (Arduino, STM32, Raspberry Pi), modèle neuroscientifique d'encodage cérébral (TRIBE v2), graphe de connaissances, mémoire sémantique, et plus encore. Liste complète dans le [`README.md` anglais - What You Can Do](README.md#what-you-can-do).

## À qui s'adresse R.A.I.N. Lab

R.A.I.N. Lab est conçu pour les personnes qui ont besoin de réponses défendables, pas simplement de réponses qui sonnent bien.

| Rôle | Ce que vous pouvez faire avec R.A.I.N. Lab |
| --- | --- |
| Fondateurs et responsables produit | Tester vos décisions stratégiques par un débat structuré avant d'engager la feuille de route ou le budget |
| Chercheurs et analystes | Comparer des hypothèses concurrentes, préserver les désaccords et conserver des pistes de raisonnement auditables |
| Opérateurs et équipes techniques | Transformer des discussions confuses en résultats vérifiables pouvant être examinés, partagés et rejoués |

En pratique, cela signifie moins d'impasses du type « l'IA l'a dit ». Vous pouvez partir d'une seule question, laisser plusieurs agents remettre en cause les hypothèses, acheminer les conflits non résolus vers un processus de vérification, et repartir avec un résultat que vous pouvez présenter en toute confiance.

## Démarrage rapide

```bash
python rain_lab.py
```

Pour les détails des commandes et de la configuration, consultez le hub docs et les références runtime.

## Voyez-le en action

Posez une question de recherche brute. Regardez quatre agents experts — James (scientifique principal), Jasmine (post-doc sceptique), Luca (géomètre) et Elena (logicienne) — en débattre en temps réel.

```
TOPIC: Could a "Phononic Morphogenetic Field" — precise acoustic interference patterns
guiding matter assembly like DNA guides cell growth — actually work?

**James:** ...phononic frequency combs could act like an acoustic blueprint for
molecular organization. The missing link between quantum coherence and biological
assembly?

**Jasmine:** Hold on. Cymatic patterns are *static* — they don't adapt to errors
or material changes the way DNA does. And the energy density needed exceeds
current acoustic levitation by *orders of magnitude*. Where's the thermal
dissipation analysis?

**Luca:** The geometry is compelling though. Wavelength spacing in phononic
combs (ωₙ₊₁ - ωₙ = 2πc/λ) parallels scalar field gradients in relic field
tomography. But macroscopic assembly requires E > 10⁴⁵ J — far beyond reach.

**Elena:** The math is elegant but the premise has a fatal flaw. The energy
density violates the Landauer limit by multiple orders of magnitude. Current
systems operate ~10³ times lower. Without experimental validation at that
scale, this remains speculation.

[Meeting continues — James responds, Jasmine pushes back, consensus forms...]
```

Rejoignez une réunion de recherche, explorez les désaccords et repartez avec des prochaines étapes — pas seulement des liens.

---

## Qualité des résultats et confiance

### Qualité des résultats (benchmarkée)

R.A.I.N. Lab suit la qualité d’ingénierie en CI et publie des définitions explicites des métriques, des lignes de base et des cibles (par exemple : nombre de panic, nombre de unwrap, taux de tests instables et couverture du chemin critique).

- Contrat des métriques de qualité : [`docs/project/quality-metrics.md`](docs/project/quality-metrics.md)
- Générateur de rapport qualité : [`scripts/ci/quality_metrics_report.py`](scripts/ci/quality_metrics_report.py)

Pour l’évaluation des résultats de recherche, nous recommandons de publier des artefacts reproductibles avant/après (jeu de tâches, baseline, grille d’évaluation, fichiers de résultats) avec ces rapports qualité.

### Confiance + confidentialité

R.A.I.N. Lab est conçu en local-first avec des paramètres sécurisés par défaut :

- chemins de workflow local/privé et options de routage vers des modèles locaux
- gateway lié à localhost par défaut, appairage activé et bind public désactivé
- posture allowlist en deny-by-default pour l’accès aux canaux
- gestion des secrets chiffrés au repos pour les clés sensibles

Documentation sécurité (comportement actuel) :

- [`docs/security/README.md`](docs/security/README.md)
- [`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md)
