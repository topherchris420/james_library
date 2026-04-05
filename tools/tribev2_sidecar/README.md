# TRIBE v2 Sidecar Service

Thin HTTP wrapper around Facebook Research's [TRIBE v2](https://github.com/facebookresearch/tribev2) brain-encoding model, designed to be called by the R.A.I.N. `tribev2_predict` tool.

## License

TRIBE v2 is licensed under **CC-BY-NC 4.0** (non-commercial use only).

## Prerequisites

- Python 3.11+
- GPU recommended (CUDA-capable) for reasonable inference times
- ~4 GB disk for model weights (downloaded on first run from HuggingFace)

## Setup

```bash
cd tools/tribev2_sidecar
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
python server.py                          # default: 127.0.0.1:8100
python server.py --port 9000              # custom port
python server.py --host 0.0.0.0           # bind to all interfaces
python server.py --cache-dir ./my_cache   # custom model cache directory
```

## R.A.I.N. Configuration

In your `config.toml`:

```toml
[tribev2]
enabled = true
endpoint = "http://127.0.0.1:8100"
timeout_secs = 120
```

## API

### `POST /predict`

```json
{
  "input_type": "video",
  "input_value": "/absolute/path/to/video.mp4"
}
```

`input_type` accepts `"video"`, `"audio"`, or `"text"`.
For video/audio, `input_value` is a file path accessible to the sidecar.
For text, `input_value` is the raw text string.

Response:

```json
{
  "shape": "(10, 20484)",
  "num_segments": 10,
  "segments": [
    {
      "index": 0,
      "mean_activation": 0.1234,
      "max_activation": 0.9876,
      "min_activation": -0.5432
    }
  ]
}
```

### `GET /health`

```json
{
  "status": "ok",
  "model_loaded": true
}
```
