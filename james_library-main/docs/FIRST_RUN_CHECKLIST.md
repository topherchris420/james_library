# First Run Checklist (LM Studio)

Use this checklist after cloning the repository.

## 1) Clone

Command:

```bash
git clone https://github.com/topherchris420/james_library.git
cd james_library
```

Expected output contains:

- `Cloning into 'james_library'...`

## 2) Run 5-minute quickstart

Linux/macOS:

```bash
bash scripts/quickstart_lmstudio.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\quickstart_lmstudio.ps1
```

Expected output contains:

- `[1/4] Checking Python...`
- `[2/4] Bootstrapping local environment...`
- `Quickstart complete.`

## 3) Run the one-screen health snapshot

Command:

```bash
python rain_lab.py --mode health
```

Expected output contains:

- `R.A.I.N. Lab Health Snapshot`
- `Overall: PASS` or `Overall: WARN`
- `LM Studio API`
- `Embedded ZeroClaw Runtime`

If output shows `Overall: FAIL`, start LM Studio and load a model first.

## 4) Run the full validation flow

Command:

```bash
python rain_lab.py --mode validate
```

Expected output contains:

- `R.A.I.N. Lab Validation`
- `Readiness:`
- `Checks:`
- `Preflight: PASS`

## 5) Optional: inspect raw preflight output directly

Command:

```bash
python rain_lab.py --mode preflight
```

Expected output contains:

- `[6/8] Checking Embedded ZeroClaw Runtime...`
- `[7/8] Checking LM Studio API...`
- `ALL SYSTEMS GO`

## 6) Optional but recommended: validate embedded ZeroClaw runtime

Command:

```bash
python rain_lab.py --mode status
```

Expected output contains:

- `ZeroClaw Status`
- `Workspace:`

If this command reports that the runtime is unavailable, install Rust and re-run `python bootstrap_local.py --skip-preflight`, or point `--zeroclaw-bin` at a prebuilt release.

## 7) Optional but recommended: inspect model catalog/status

Command:

```bash
python rain_lab.py --mode models
```

Expected output contains:

- `Provider:`
- `Model:`

## 8) Start first chat session

Command:

```bash
python rain_lab.py --mode chat --topic "first-run smoke test"
```

Expected output contains:

- a model response (non-empty answer text)

## 9) Optional machine-readable validation output

Command:

```bash
python rain_lab.py --mode validate -- --json
```

Expected output contains:

- `"overall_status"`
- `"health_checks"`
- `"recommended_actions"`
