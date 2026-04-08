from __future__ import annotations

from pathlib import Path

from james_library.launcher import swarm_orchestrator as orchestrator
from james_library.utilities import prefetch


def test_extract_file_paths_finds_code_paths_in_prompt(tmp_path: Path) -> None:
    workspace = tmp_path
    target = workspace / "src" / "agent" / "history.rs"
    target.parent.mkdir(parents=True)
    target.write_text("pub fn estimate_history_tokens() {}\n", encoding="utf-8")

    prompt = "Please inspect `src/agent/history.rs` and summarize the memory path."

    paths = prefetch.extract_file_paths(prompt, workspace)

    assert paths == [target.resolve()]


def test_build_prefetch_context_includes_dependency_signatures(tmp_path: Path) -> None:
    workspace = tmp_path
    main_file = workspace / "app.py"
    dep_file = workspace / "helpers.py"
    main_file.write_text("from helpers import useful\nprint(useful())\n", encoding="utf-8")
    dep_file.write_text("def useful():\n    return 42\n", encoding="utf-8")

    def fake_lsp_query(action: str, file_path: str, **_: object) -> dict[str, object]:
        resolved = Path(file_path).resolve()
        if action == "document_symbols" and resolved == main_file.resolve():
            return {
                "results": [
                    {"name": "main", "kind": "function"},
                ]
            }
        if action == "document_symbols" and resolved == dep_file.resolve():
            return {
                "results": [
                    {"name": "useful", "kind": "function"},
                ]
            }
        return {"results": []}

    context = prefetch.build_prefetch_context(
        prompt=f"Review {main_file.name} before coding.",
        workspace_root=workspace,
        lsp_query=fake_lsp_query,
    )

    assert "[IDE VISION]" in context
    assert "app.py" in context
    assert "helpers.py" in context
    assert "useful" in context


def test_specialist_prompt_injects_prefetch_context_on_first_turn(tmp_path: Path) -> None:
    workspace = tmp_path
    target = workspace / "src" / "tools" / "lsp_tool.rs"
    target.parent.mkdir(parents=True)
    target.write_text("pub struct LspTool;\n", encoding="utf-8")

    manifest = orchestrator.AgentManifest(
        schema_version="1",
        identity=orchestrator.AgentIdentity(
            agent_id="architect",
            display_name="Architect",
            role="Rust systems architect",
            system_prompt="Be precise.",
        ),
    )

    prompt = orchestrator._build_specialist_user_message(
        query="Inspect src/tools/lsp_tool.rs and propose the next fix.",
        manifest=manifest,
        room_context="shared room context",
        prefetch_context="[IDE VISION]\n- src/tools/lsp_tool.rs: LspTool (struct)",
    )

    assert "shared room context" in prompt
    assert "[IDE VISION]" in prompt
    assert "LspTool" in prompt
    assert "Rust systems architect" in prompt


def test_compact_messages_for_llm_logs_context_savings() -> None:
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Old safe turn " * 40},
        {"role": "assistant", "content": "Old safe reply " * 40},
        {"role": "user", "content": "Recent turn A"},
        {"role": "assistant", "content": "Recent reply A"},
        {"role": "user", "content": "Recent turn B"},
        {"role": "assistant", "content": "Recent reply B"},
        {"role": "user", "content": "Recent turn C"},
        {"role": "assistant", "content": "Recent reply C"},
    ]

    compacted, meta = orchestrator._compact_messages_for_llm(messages, max_context_tokens=80)

    assert compacted[0]["role"] == "system"
    assert meta["original_tokens"] >= meta["compacted_tokens"]
    assert "[CONTEXT]" in meta["log_message"]
