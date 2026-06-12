# Point d'entrée de la documentation R.A.I.N. Lab (FR)

<p align="center">
  <a href="https://github.com/topherchris420/james_library/actions/workflows/ci.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/tests.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/tests.yml/badge.svg?branch=main" alt="Tests" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml/badge.svg?branch=main" alt="Docs" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml/badge.svg?branch=main" alt="Security Audit" /></a>
</p>

> Cette page est le point d'entrée français, aligné sur le README principal et l'architecture docs.

## Navigation

- README principal : [`README.md`](README.md)
- Hub docs (FR) : [`docs/README.fr.md`](docs/README.fr.md)
- Table des matières unifiée : [`docs/SUMMARY.md`](docs/SUMMARY.md)

## Carte rapide d'identité du projet

- **R.A.I.N. Lab** : l'expérience produit côté utilisateur final
- **James Library** : la couche Python de recherche/workflows
- **R.A.I.N.** : la couche runtime Rust (crate `R.A.I.N.`)

Flux d'exécution : `Utilisateur -> interface R.A.I.N. Lab -> runtime R.A.I.N. -> workflows de recherche James Library -> API modèle/provider`

## Vue d'ensemble des fonctionnalités

James n'est pas un simple chat multi-agents — c'est un véritable système d'exploitation pour la recherche : 10+ fournisseurs de modèles, 25+ plateformes de messagerie, 60+ outils intégrés, contrôle matériel (Arduino, STM32, Raspberry Pi), modèle neuroscientifique d'encodage cérébral (TRIBE v2), graphe de connaissances, mémoire sémantique, et plus encore. Liste complète dans le [`README.md` anglais - What It Does](README.md#what-it-does).

## À qui s'adresse R.A.I.N. Lab

R.A.I.N. Lab est conçu pour les personnes qui ont besoin de réponses défendables, pas simplement de réponses qui sonnent bien.

| Rôle | Ce que vous pouvez faire avec R.A.I.N. Lab |
| --- | --- |
| Fondateurs et responsables produit | Tester vos décisions stratégiques par un débat structuré avant d'engager la feuille de route ou le budget |
| Chercheurs et analystes | Comparer des hypothèses concurrentes, préserver les désaccords et conserver des pistes de raisonnement auditables |
| Opérateurs et équipes techniques | Transformer des discussions confuses en résultats vérifiables pouvant être examinés, partagés et rejoués |

## En quoi c'est différent

| Outil de recherche classique | R.A.I.N. Lab |
| --- | --- |
| Retourne une liste d'articles | Retourne un débat |
| Considère la première réponse plausible comme correcte | Préserve le désaccord jusqu'à résolution par les preuves |
| Un seul point de vue, un seul modèle | Quatre voix avec des expertises et contraintes différentes |
| Cloud-first | Fonctionne entièrement en local si vous le souhaitez |

## Workflow local et privé

R.A.I.N. Lab fonctionne entièrement sur votre propre matériel. Connectez un modèle local via [LM Studio](https://lmstudio.ai/) ou [Ollama](https://ollama.com/) — aucun appel cloud, aucune télémétrie, aucun partage de données.

## Démarrage rapide

**Démo en ligne :** [rainlabteam.vercel.app](https://rainlabteam.vercel.app/) — aucune installation requise

```bash
python rain_lab.py
```

Windows : double-cliquez sur `INSTALL_RAIN.cmd`.
macOS/Linux : exécutez `./install.sh`.

Pour les détails des commandes et de la configuration, consultez le hub docs et les références runtime.

## Prérequis

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommandé) ou pip
- Toolchain Rust (optionnel, pour la couche runtime ZeroClaw)
- Un modèle local via [LM Studio](https://lmstudio.ai/) ou [Ollama](https://ollama.com/) (optionnel — le mode démo fonctionne sans)

## Documentation

| | |
|---|---|
| **Premiers pas** | [Commencer ici](START_HERE.md) -- [Guide débutant](docs/getting-started/README.md) -- [Installation en un clic](docs/one-click-bootstrap.md) -- [Dépannage](docs/troubleshooting.md) |
| **Articles** | [Archives de recherche](https://topherchris420.github.io/research/) |
| **Autres langues** | [English](README.md) -- [简体中文](README.zh-CN.md) -- [日本語](README.ja.md) -- [Русский](README.ru.md) -- [Tiếng Việt](README.vi.md) |

## Pour les développeurs

Pour l'architecture, les points d'extension et la contribution, consultez le [`README.md` anglais - For Developers](README.md#for-developers), [ARCHITECTURE.md](ARCHITECTURE.md) et [CLAUDE.md](CLAUDE.md).

## Remerciements

Un grand merci à l'équipe **ZeroClaw** pour le moteur runtime Rust qui propulse R.A.I.N. Lab. Voir le répertoire `crates/` pour les composants du runtime ZeroClaw.

---

**Licence :** MIT -- [Vers3Dynamics](https://vers3dynamics.com/)
