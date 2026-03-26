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

## Capacités en un coup d’œil (Capabilities At A Glance)

Cette page est la porte d’entrée. Pour la surface runtime complète (commandes, channels, providers, opérations, sécurité, matériel), utilisez les références ci-dessous.

| Domaine de capacité | Ce que vous obtenez | Référence canonique |
| --- | --- | --- |
| CLI et automatisation | Onboarding, agent, gateway/daemon, service, diagnostics, estop, cron, skills, mises à jour | [Commands Reference](docs/reference/cli/commands-reference.md) |
| Channels et messagerie | Distribution multi-channel, allowlists, modes webhook/polling, config par channel | [Channels Reference](docs/reference/api/channels-reference.md) |
| Providers et routage de modèles | Providers local/cloud, alias, variables d’authentification, rafraîchissement des modèles | [Providers Reference](docs/reference/api/providers-reference.md) |
| Configuration et contrats runtime | Schéma de configuration et garanties de comportement | [Config Reference](docs/reference/api/config-reference.md) |
| Opérations et dépannage | Runbook, modèles de déploiement, diagnostics et reprise sur incident | [Operations Runbook](docs/ops/operations-runbook.md), [Troubleshooting](docs/ops/troubleshooting.md) |
| Modèle de sécurité | Sandbox, frontières de politiques, posture d’audit | [Security Docs Hub](docs/security/README.md) |
| Matériel et périphériques | Configuration des cartes et design des outils périphériques | [Hardware Docs Hub](docs/hardware/README.md) |

## Qui doit lire quoi ensuite (Who Should Read What Next)

- **Nouveaux utilisateurs / première expérience** : commencez par [`START_HERE.md`](START_HERE.md), puis [`docs/getting-started/README.md`](docs/getting-started/README.md), puis [`docs/troubleshooting.md`](docs/troubleshooting.md).
- **Opérateurs / responsables déploiement** : priorisez [`docs/ops/operations-runbook.md`](docs/ops/operations-runbook.md), [`docs/ops/network-deployment.md`](docs/ops/network-deployment.md), [`docs/security/README.md`](docs/security/README.md).
- **Intégrateurs / développeurs d'extensions** : priorisez [`docs/reference/cli/commands-reference.md`](docs/reference/cli/commands-reference.md), [`docs/reference/api/providers-reference.md`](docs/reference/api/providers-reference.md), [`docs/reference/api/channels-reference.md`](docs/reference/api/channels-reference.md).
