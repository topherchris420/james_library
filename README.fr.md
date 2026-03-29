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
