import os
import sys
import json
import asyncio
from pydantic import BaseModel, Field
from typing import List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# TCP port must match Rust's KAIROS_TCP_PORT (48765 on Windows)
IS_WINDOWS = os.name == "nt"
TCP_PORT = 48765
SOCKET_PATH = "/tmp/kairos_dreamer.sock"


class KnowledgeNode(BaseModel):
    entity: str = Field(description="The core subject")
    relationship: str = Field(description="How it relates")
    target: str = Field(description="The object of the relationship")
    context: str = Field(description="Dense summary of the memory")


class KairosConsolidation(BaseModel):
    compressed_nodes: List[KnowledgeNode]


async def process_batch(rows: List[dict]) -> dict:
    """Process batch and return KairosBatchResponse-compatible dict."""
    if not rows:
        return {"source_ids": [], "facts": []}

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Extract factual assertions, preferences, and states into dense knowledge nodes. "
            "Ignore pleasantries."
        )),
        ("human", "Raw logs:\n{raw_logs}")
    ])
    chain = prompt | llm.with_structured_output(KairosConsolidation)

    script = "\n".join([
        f"[{m.get('created_at', '')}] {m.get('role', 'user')}: {m.get('content', '')}"
        for m in rows
    ])
    source_ids = [m.get("id") for m in rows if "id" in m]

    try:
        result = await chain.ainvoke({"raw_logs": script})
        facts = [
            {"entity": node.entity, "relationship": node.relationship, "target": node.target, "context": node.context}
            for node in result.compressed_nodes
        ]
        return {"source_ids": source_ids, "facts": facts}
    except Exception as e:
        print(f"[KAIROS ERROR] {e}", file=sys.stderr)
        return {"source_ids": source_ids, "facts": []}


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle IPC connection from Rust daemon. Rust sends one JSON line + newline."""
    try:
        data = await reader.readline()
        if not data:
            return

        payload = json.loads(data.decode("utf-8").strip())
        # Rust KairosBatchRequest has 'request_id' and 'rows'
        rows = payload.get("rows", [])
        print(f"[KAIROS] Processing batch of {len(rows)} memories...")

        response = await process_batch(rows)

        # Send JSON response followed by newline (Rust reads with read_line)
        writer.write(json.dumps(response).encode("utf-8"))
        writer.write(b"\n")
        await writer.drain()
        print("[KAIROS] Response sent to Rust daemon.")
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        print(f"[KAIROS DECODE ERROR] {e}", file=sys.stderr)
        writer.write(b'{"source_ids": [], "facts": []}\n')
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    if IS_WINDOWS:
        server = await asyncio.start_server(handle_client, "127.0.0.1", TCP_PORT)
        print(f"[KAIROS] Listening on TCP {TCP_PORT} (Windows)")
    else:
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        server = await asyncio.start_unix_server(handle_client, path=SOCKET_PATH)
        print(f"[KAIROS] Listening on UDS {SOCKET_PATH}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
