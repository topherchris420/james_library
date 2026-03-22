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

## Démarrage rapide

```bash
python rain_lab.py
```

Pour les détails des commandes et de la configuration, consultez le hub docs et les références runtime.
