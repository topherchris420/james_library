# Référence des commandes (FR)

Commande principale:

```bash
python rain_lab.py
```

Modes principaux:

- `--mode first-run`
- `--mode chat --topic "..."`
- `--mode validate`
- `--mode status`
- `--mode models`
- `--mode backup -- --json`

## Commandes du pont runtime ZeroClaw

Point d'entrée pour le runtime Rust:

```bash
zeroclaw gateway
zeroclaw daemon
```

Notes:

- `zeroclaw gateway` et `zeroclaw daemon` utilisent le port `4200` par défaut quand `--port` n'est pas fourni.
- Le démarrage est bloqué si l'arrêt d'urgence est actif au niveau `kill-all` ou `network-kill`.

Voir aussi: [`troubleshooting.fr.md`](troubleshooting.fr.md).
