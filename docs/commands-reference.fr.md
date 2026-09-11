# Référence des commandes (FR)

Commande principale:

```bash
python rain_lab.py
```

Modes principaux:

- `--mode first-run`
- `--mode chat --topic "..."`
- `--mode chat --topic "..." --temp 0.85 --max-tokens 320` pour des sorties d'expérimentation plus exploratoires
- `--mode validate`
- `--mode status`
- `--mode models`
- `--mode backup -- --json`

Dans les réunions en mode chat, les répétitions persistantes déclenchent une
demande de preuves, puis une hypothèse alternative réfutable, puis une conclusion
anticipée si nécessaire. Chaque tentative laisse un tour complet au groupe ;
la conclusion ne relance pas le débat et respecte la limite totale de tours.
Les actions sont enregistrées dans le fichier de session. Voir
[la reprise adaptative des réunions](meeting-recovery.md) (en anglais).

## Commandes du pont runtime R.A.I.N.

Point d'entrée pour le runtime Rust:

```bash
R.A.I.N. gateway
R.A.I.N. daemon
```

Notes:

- `R.A.I.N. gateway` et `R.A.I.N. daemon` utilisent `gateway.port` depuis la config quand `--port` n'est pas fourni.
- Pour un pont Body-daemon par défaut, définissez `gateway.port = 4200` dans la config ou `R.A.I.N._GATEWAY_PORT=4200` dans l'environnement.
- Le démarrage est bloqué si l'arrêt d'urgence est actif au niveau `kill-all` ou `network-kill`.

Voir aussi: [`troubleshooting.fr.md`](troubleshooting.fr.md).
