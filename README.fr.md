# Point d’entrée de la documentation R.A.I.N. Lab (FR)

> Cette page est le point d’entrée français, aligné sur le README principal et l’architecture docs.

## Navigation

- README principal : [`README.md`](README.md)
- Hub docs (FR) : [`docs/README.fr.md`](docs/README.fr.md)
- Table des matières unifiée : [`docs/SUMMARY.md`](docs/SUMMARY.md)

## Carte rapide d'identité du projet

- **R.A.I.N. Lab** : l'expérience produit côté utilisateur final
- **James Library** : la couche Python de recherche/workflows
- **ZeroClaw** : la couche runtime Rust (crate `zeroclaw`)

Flux d'exécution : `Utilisateur -> interface R.A.I.N. Lab -> runtime ZeroClaw -> workflows de recherche James Library -> API modèle/provider`

## Démarrage rapide

```bash
python rain_lab.py
```

Pour les détails des commandes et de la configuration, consultez le hub docs et les références runtime.
