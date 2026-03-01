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

- `[1/5] Checking Python...`
- `[3/5] Installing dependencies...`
- `Quickstart complete.`

## 3) Confirm LM Studio endpoint is reachable

Command:

```bash
python rain_health_check.py
```

Expected output contains:

- `R.A.I.N. Lab Health Check`
- `Overall: PASS` or `Overall: WARN`
- `LM Studio API`

If output shows `Overall: FAIL`, start LM Studio and load a model first.

## 4) Run project preflight

Command:

```bash
python rain_lab.py --mode preflight
```

Expected output contains:

- `[6/7] Checking LM Studio API...`
- `ALL SYSTEMS GO`

## 5) Start first chat session

Command:

```bash
python rain_lab.py --mode chat --topic "first-run smoke test"
```

Expected output contains:

- a model response (non-empty answer text)

## 6) Optional runtime health snapshot (JSON)

Command:

```bash
python rain_health_check.py --json
```

Expected output contains:

- `"overall_status"`
- `"checks"`
