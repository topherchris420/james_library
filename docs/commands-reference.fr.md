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

## Jugement typé

```bash
python rain_lab.py judge --evidence cycle.json
python rain_lab.py judge --replay meeting_archives/session_artifacts/session_<id>.json
```

Cette commande applique la limite stricte de promotion à un paquet de preuves
sélectionné. L'accès distant est désactivé par défaut et la relecture enregistrée
n'appelle jamais de fournisseur. Voir [`typed-judgment.md`](typed-judgment.md).

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

## R.A.I.N. Rig (optionnel)

Rig est une couche de nœud facultative du runtime Rust ; `python rain_lab.py`
n'en dépend pas. Voir [`rig/README.md`](rig/README.md).

```bash
rain rig status [--json]          # état du nœud (READY/DEGRADED/BLOCKED)
rain rig doctor [--json]          # PASS/WARN/FAIL/SKIP ; code de sortie non nul si FAIL
rain rig models [--json]          # modèles sur llama.cpp / Ollama / LM Studio / réunion
rain rig capabilities [--json]    # registre des capacités et état courant
rain rig peers [--json]           # identité partageable et transports pairs
rain rig setup [--profile local|node|field] [--node-name NOM] [--privacy local|hybrid|hosted] [--yes] [--dry-run]
rain rig up [--dry-run]           # démarre le démon R.A.I.N. sur son adresse configurée
rain rig radio status|encode|decode   # modem logiciel Skybridge (expérimental, aucune émission RF)
```

- La découverte ne sonde que des adresses locales (loopback ou réseau privé) et
  ne contacte jamais de service hébergé.
- `setup` demande confirmation avant d'écrire `config.toml` (`--yes` requis en
  mode non interactif) et n'installe ni ne télécharge rien.
- `up` ne démarre que le démon R.A.I.N. ; un nœud BLOCKED ne démarre rien.
