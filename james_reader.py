"""
James Reader - Headless CLI for research document exploration.

This script extracts the core reasoning and search logic from the agentic-file-search
tool and adapts it for the Vers3Dynamics research platform. It runs non-interactively
without any Streamlit UI dependencies.

Usage:
    python james_reader.py --topic "Scalar Resonance" --path ./downloads
    python james_reader.py --topic "Havana Syndrome" --path "C:/Users/chris/Downloads/files"
"""

import argparse
import asyncio
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from docling.document_converter import DocumentConverter
from google.genai import Client as GenAIClient
from google.genai.types import Content, HttpOptions, Part
from pydantic import BaseModel
from typing import Literal, TypeAlias


# =============================================================================
# Configuration
# =============================================================================

# Supported document extensions
SUPPORTED_EXTENSIONS: frozenset = frozenset({".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".html", ".md"})

DEFAULT_PREVIEW_CHARS = 3000
DEFAULT_SCAN_PREVIEW_CHARS = 1500
DEFAULT_MAX_WORKERS = 4

# Document cache
_DOCUMENT_CACHE: dict[str, str] = {}


# =============================================================================
# Models
# =============================================================================

Tools: TypeAlias = Literal[
    "read", "grep", "glob", "scan_folder",
    "preview_file", "parse_file"
]
ActionType: TypeAlias = Literal["stop", "godeeper", "toolcall", "askhuman"]


class StopAction(BaseModel):
    final_result: str


class AskHumanAction(BaseModel):
    question: str


class GoDeeperAction(BaseModel):
    directory: str


class ToolCallArg(BaseModel):
    parameter_name: str
    parameter_value: Any


class ToolCallAction(BaseModel):
    tool_name: Tools
    tool_input: list[ToolCallArg]

    def to_fn_args(self) -> dict:
        return {arg.parameter_name: arg.parameter_value for arg in self.tool_input}


class Action(BaseModel):
    action: ToolCallAction | GoDeeperAction | StopAction | AskHumanAction
    reason: str

    def to_action_type(self) -> ActionType:
        if isinstance(self.action, ToolCallAction):
            return "toolcall"
        elif isinstance(self.action, GoDeeperAction):
            return "godeeper"
        elif isinstance(self.action, AskHumanAction):
            return "askhuman"
        return "stop"


# =============================================================================
# Token Usage Tracking
# =============================================================================

GEMINI_FLASH_INPUT_COST_PER_MILLION = 0.075
GEMINI_FLASH_OUTPUT_COST_PER_MILLION = 0.30


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    documents_scanned: int = 0
    documents_parsed: int = 0

    def add_api_call(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens
        self.api_calls += 1

    def summary(self) -> str:
        input_cost = (self.prompt_tokens / 1_000_000) * GEMINI_FLASH_INPUT_COST_PER_MILLION
        output_cost = (self.completion_tokens / 1_000_000) * GEMINI_FLASH_OUTPUT_COST_PER_MILLION
        return f"""
═══════════════════════════════════════════════════════════════
                      TOKEN USAGE SUMMARY
═══════════════════════════════════════════════════════════════
  API Calls:           {self.api_calls}
  Prompt Tokens:       {self.prompt_tokens:,}
  Completion Tokens:  {self.completion_tokens:,}
  Total Tokens:       {self.total_tokens:,}
  Documents Scanned:  {self.documents_scanned}
  Documents Parsed:   {self.documents_parsed}
───────────────────────────────────────────────────────────────
  Est. Cost (Gemini Flash):
    Input:  ${input_cost:.4f}
    Output: ${output_cost:.4f}
    Total:  ${input_cost + output_cost:.4f}
═══════════════════════════════════════════════════════════════
"""


# =============================================================================
# Filesystem Operations
# =============================================================================

def describe_dir_content(directory: str) -> str:
    """Describe the contents of a directory."""
    if not os.path.exists(directory) or not os.path.isdir(directory):
        return f"No such directory: {directory}"

    children = os.listdir(directory)
    if not children:
        return f"Directory {directory} is empty"

    files = []
    directories = []

    for child in children:
        fullpath = os.path.join(directory, child)
        if os.path.isfile(fullpath):
            files.append(fullpath)
        else:
            directories.append(fullpath)

    description = f"Content of {directory}\n"
    description += "FILES:\n- " + "\n- ".join(files)

    if not directories:
        description += "\nThis folder does not have any sub-folders"
    else:
        description += "\nSUBFOLDERS:\n- " + "\n- ".join(directories)

    return description


def read_file(file_path: str) -> str:
    """Read a plain text file."""
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return f"No such file: {file_path}"
    with open(file_path, "r") as f:
        return f.read()


def grep_file_content(file_path: str, pattern: str) -> str:
    """Search for a regex pattern in a file."""
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return f"No such file: {file_path}"
    with open(file_path, "r") as f:
        content = f.read()
    regex = re.compile(pattern=pattern, flags=re.MULTILINE)
    matches = regex.findall(content)
    if matches:
        return f"MATCHES for {pattern} in {file_path}:\n\n- " + "\n- ".join(matches)
    return "No matches found"


def glob_paths(directory: str, pattern: str) -> str:
    """Find files matching a glob pattern."""
    if not os.path.exists(directory) or not os.path.isdir(directory):
        return f"No such directory: {directory}"
    search_path = Path(directory) / pattern
    matches = list(Path(directory).glob(pattern))
    if matches:
        return "MATCHES:\n\n- " + "\n- ".join(str(m) for m in matches)
    return "No matches found"


def _get_cached_or_parse(file_path: str) -> str:
    """Get document content from cache or parse it."""
    abs_path = os.path.abspath(file_path)
    cache_key = f"{abs_path}:{os.path.getmtime(abs_path)}"

    if cache_key not in _DOCUMENT_CACHE:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        _DOCUMENT_CACHE[cache_key] = result.document.export_to_markdown()

    return _DOCUMENT_CACHE[cache_key]


def preview_file(file_path: str, max_chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """Quick preview of a document."""
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return f"No such file: {file_path}"

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return f"Unsupported: {ext}"

    try:
        full_content = _get_cached_or_parse(file_path)
        preview = full_content[:max_chars]
        if len(full_content) > max_chars:
            preview += f"\n\n[... {len(full_content):,} chars total ...]"
        return f"=== PREVIEW of {file_path} ===\n\n{preview}"
    except Exception as e:
        return f"Error: {e}"


def parse_file(file_path: str) -> str:
    """Full content of a document."""
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return f"No such file: {file_path}"

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return f"Unsupported: {ext}"

    try:
        return _get_cached_or_parse(file_path)
    except Exception as e:
        return f"Error parsing: {e}"


def _preview_single_file(file_path: str, preview_chars: int) -> dict:
    """Helper for parallel scanning."""
    filename = os.path.basename(file_path)
    try:
        content = _get_cached_or_parse(file_path)
        preview = content[:preview_chars]
        return {"file": file_path, "filename": filename, "preview": preview, "status": "success"}
    except Exception as e:
        return {"file": file_path, "filename": filename, "preview": "", "status": f"error: {e}"}


def scan_folder(directory: str, max_workers: int = DEFAULT_MAX_WORKERS, preview_chars: int = DEFAULT_SCAN_PREVIEW_CHARS) -> str:
    """Scan all documents in a folder in parallel."""
    if not os.path.exists(directory) or not os.path.isdir(directory):
        return f"No such directory: {directory}"

    doc_files = []
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        if os.path.isfile(item_path):
            ext = os.path.splitext(item)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                doc_files.append(item_path)

    if not doc_files:
        return f"No documents found in {directory}"

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_preview_single_file, f, preview_chars): f for f in doc_files}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda x: x["filename"])

    output = [f"SCAN: {directory} ({len(results)} documents)"]
    for r in results:
        output.append(f"  - {r['filename']}: {r['status']}")
        if r['status'] == 'success' and r['preview']:
            output.append(f"    Preview: {r['preview'][:200]}...")

    return "\n".join(output)


# =============================================================================
# Tool Registry
# =============================================================================

TOOLS: dict[Tools, Callable[..., str]] = {
    "read": read_file,
    "grep": grep_file_content,
    "glob": glob_paths,
    "scan_folder": scan_folder,
    "preview_file": preview_file,
    "parse_file": parse_file,
}


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """
You are FsExplorer, an AI agent that explores filesystems to answer user questions about documents.

## Available Tools
| Tool | Purpose |
|------|---------|
| scan_folder | Scan ALL documents in a folder in parallel |
| preview_file | Quick preview of a document (~first page) |
| parse_file | Full content of a document |
| read | Read a plain text file |
| grep | Search for a pattern in a file |
| glob | Find files matching a pattern |

## Document Exploration Strategy

### Phase 1: Parallel Scan
When you encounter a folder with documents, use `scan_folder` to scan ALL documents at once.

### Phase 2: Deep Dive
Use `parse_file` on relevant documents. Watch for cross-references to other documents.

### Phase 3: Backtracking
If a document references another, use `parse_file` to read it too.

## Citation Requirements
When providing your final answer, cite sources using: [Source: filename]

Example:
> The mechanism involves scalar waves [Source: scalar_resonance.pdf]

## Final Answer Structure
1. Direct answer to the user's question
2. Details with inline citations
3. Sources section listing all documents consulted
"""


# =============================================================================
# Agent Implementation
# =============================================================================

class ResearcherAgent:
    """
    Headless agent for exploring research documents.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-001") -> None:
        """Initialize the agent with API credentials."""
        self._client = GenAIClient(
            api_key=api_key,
            http_options=HttpOptions(api_version="v1"),
        )
        self._model = model
        self._chat_history: list[Content] = []
        self.token_usage = TokenUsage()
        self.step_count = 0
        self.documents_referenced: list[str] = []

    def configure_task(self, task: str) -> None:
        """Add a task message to the conversation history."""
        self._chat_history.append(
            Content(role="user", parts=[Part.from_text(text=task)])
        )

    async def take_action(self) -> tuple[Action, ActionType] | None:
        """Request the next action from the AI model."""
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=self._chat_history,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": Action,
            },
        )

        if response.usage_metadata:
            self.token_usage.add_api_call(
                prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                completion_tokens=response.usage_metadata.candidates_token_count or 0,
            )

        if response.candidates is not None:
            if response.candidates[0].content is not None:
                self._chat_history.append(response.candidates[0].content)
            if response.text is not None:
                action = Action.model_validate_json(response.text)
                if action.to_action_type() == "toolcall":
                    toolcall = action.action
                    self.call_tool(
                        tool_name=toolcall.tool_name,
                        tool_input=toolcall.to_fn_args(),
                    )
                return action, action.to_action_type()

        return None

    def call_tool(self, tool_name: Tools, tool_input: dict) -> None:
        """Execute a tool and add the result to conversation history."""
        try:
            result = TOOLS[tool_name](**tool_input)
        except Exception as e:
            result = f"Error: {e}"

        # Track documents
        if tool_name == "scan_folder":
            self.token_usage.documents_scanned += result.count("SCAN:")
        elif tool_name == "parse_file":
            self.token_usage.documents_parsed += 1
            # Track referenced document
            file_path = tool_input.get("file_path", "")
            if file_path:
                self.documents_referenced.append(os.path.basename(file_path))

        self._chat_history.append(
            Content(
                role="user",
                parts=[Part.from_text(text=f"Tool result for {tool_name}:\n\n{result}")],
            )
        )


# =============================================================================
# Research Workflow
# =============================================================================

async def run_research(topic: str, path: str, model: str, max_steps: int = 20) -> None:
    """Execute the research workflow."""

    # Resolve and validate path
    root_dir = os.path.abspath(path)
    if not os.path.exists(root_dir) or not os.path.isdir(root_dir):
        print(f"ERROR: No such directory: {root_dir}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"James Reader - Research Analysis")
    print(f"{'='*60}")
    print(f"Topic: {topic}")
    print(f"Path: {root_dir}")
    print(f"Model: {model}")
    print(f"{'='*60}\n")

    # Initialize agent with API key
    api_key = os.getenv("ZEROCLAW_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: ZEROCLAW_API_KEY or OPENAI_API_KEY not found in environment")
        sys.exit(1)

    agent = ResearcherAgent(api_key=api_key, model=model)

    # Initial task
    dir_description = describe_dir_content(root_dir)
    agent.configure_task(
        f"Current directory ('{root_dir}') looks like:\n\n{dir_description}\n\n"
        f"Task: '{topic}'. What action should you take first?"
    )

    print("[*] Starting research workflow...\n")

    # Run the agent loop
    for step in range(max_steps):
        agent.step_count = step + 1
        print(f"[*] Step {agent.step_count}: Processing...")

        result = await agent.take_action()

        if result is None:
            print("[!] Agent returned no action")
            break

        action, action_type = result

        if action_type == "toolcall":
            toolcall = action.action
            print(f"    Tool: {toolcall.tool_name}")
            print(f"    Reason: {action.reason[:100]}..." if len(action.reason) > 100 else f"    Reason: {action.reason}")

        elif action_type == "stop":
            final_result = action.action.final_result
            print(f"\n{'='*60}")
            print(f"FINAL ANSWER")
            print(f"{'='*60}\n")
            print(final_result)
            print(f"\n{'='*60}")
            print(agent.token_usage.summary())

            if agent.documents_referenced:
                unique_docs = list(set(agent.documents_referenced))
                print("Documents Referenced:")
                for doc in unique_docs:
                    print(f"  - {doc}")
            print(f"{'='*60}\n")
            return

        elif action_type == "godeeper":
            print(f"    Navigate: {action.action.directory}")
            # Update the agent with new directory context
            new_dir = action.action.directory
            if os.path.isdir(new_dir):
                dir_description = describe_dir_content(new_dir)
                agent.configure_task(
                    f"Current directory ('{new_dir}') looks like:\n\n{dir_description}\n\n"
                    f"Task: '{topic}'. What action should you take next?"
                )

        elif action_type == "askhuman":
            # For headless mode, auto-answer with "continue"
            print(f"    Question: {action.action.question}")
            print("    [Auto-answering for headless mode]")
            agent.configure_task("Please continue with the task.")

    print("[!] Reached maximum steps without final answer")
    print(agent.token_usage.summary())


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="James Reader - Headless research document analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python james_reader.py --topic "Scalar Resonance" --path ./downloads
  python james_reader.py --topic "Havana Syndrome" --path "C:/Users/chris/Downloads/files"
  python james_reader.py --topic "Coherence" --path ./library --model "google/gemini-2.0-flash-001"
"""
    )

    parser.add_argument(
        "--topic", "-t",
        required=True,
        help="The research question or topic to investigate"
    )

    parser.add_argument(
        "--path", "-p",
        default="./library",
        help="Folder containing PDFs/TXT/MD files to search (default: ./library)"
    )

    parser.add_argument(
        "--model", "-m",
        default="gemini-2.0-flash-001",
        help="Model to use (default: gemini-2.0-flash-001)"
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum agent steps (default: 20)"
    )

    args = parser.parse_args()

    # Run the async workflow
    asyncio.run(run_research(
        topic=args.topic,
        path=args.path,
        model=args.model,
        max_steps=args.max_steps
    ))


if __name__ == "__main__":
    main()
