# James Reader

A standalone, headless CLI tool for AI-powered research on local documents.

James Reader uses an AI agent to search, read, and analyze documents in your local folders. It performs multi-step reasoning to find relevant information and provide cited answers.

## Features

- **AI-Powered Research** - Uses Google Gemini to intelligently search and analyze documents
- **Multi-Format Support** - Reads PDF, DOCX, DOC, PPTX, XLSX, HTML, MD, TXT
- **3-Phase Strategy** - Parallel scan → Deep dive → Backtracking for cross-references
- **Headless Operation** - CLI-only, no UI, perfect for automation
- **Token Tracking** - Reports API usage and estimated costs
- **Source Citations** - Provides inline citations with filenames

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/topherchris420/james_library.git
cd james_library
```

### 2. Install Dependencies

```bash
pip install -r requirements-reader.txt
```

### 3. Set Your API Key

James Reader uses Google Gemini. Set your API key via environment variable:

```bash
# Linux/macOS
export ZEROCLAW_API_KEY="your-google-api-key"

# Windows (PowerShell)
$env:ZEROCLAW_API_KEY="your-google-api-key"

# Or use OPENAI_API_KEY if you have an OpenAI key
export OPENAI_API_KEY="your-openai-key"
```

Get a Google API key at: https://aistudio.google.com/app/apikey

### 4. Run a Query

```bash
python james_reader.py --topic "Your research question" --path ./documents
```

## Usage

```
python james_reader.py --topic "QUERY" --path "FOLDER" [OPTIONS]

Arguments:
  --topic, -t          Research question or topic (required)
  --path, -p           Folder containing documents (default: ./library)
  --model, -m          Model to use (default: gemini-2.0-flash-001)
  --max-steps          Max agent steps (default: 20)

Example:
  python james_reader.py --topic "Scalar Resonance" --path ./research_papers
  python james_reader.py -t "Havana Syndrome" -p "C:/Users/chris/Downloads/files"
```

## How It Works

1. **Scan** - Agent scans all documents in the folder in parallel
2. **Analyze** - Agent identifies relevant documents based on your query
3. **Deep Read** - Agent parses and analyzes relevant documents in detail
4. **Cross-Reference** - Agent follows references to other documents if needed
5. **Answer** - Agent provides a synthesized answer with source citations

## Output Example

```
============================================================
James Reader - Research Analysis
============================================================
Topic: What is scalar resonance?
Path: /home/user/research
Model: gemini-2.0-flash-001
============================================================

[*] Starting research workflow...

[*] Step 1: Processing...
    Tool: scan_folder
    Reason: Scanning all documents to find relevant content...

[*] Step 2: Processing...
    Tool: parse_file
    Reason: Reading document about physics mechanisms...

============================================================
FINAL ANSWER
============================================================

Scalar resonance is [answer with citations]...

Sources:
- scalar_resonance.pdf
- physics_theory.md

============================================================
```

## Requirements

- Python 3.10+
- Google API key (or OpenAI API key)
- See `requirements-reader.txt` for Python dependencies

## Files

| File | Description |
|------|-------------|
| `james_reader.py` | Main CLI script |
| `requirements-reader.txt` | Python dependencies |

## License

MIT License
