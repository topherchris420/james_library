"""CLI entry point for R.A.I.N.-tools."""

from __future__ import annotations

import argparse
import asyncio
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="R.A.I.N.-tools",
        description="R.A.I.N. LangGraph-based tool calling CLI",
    )
    parser.add_argument(
        "message",
        nargs="*",
        default=[],
        help="Message to send to the agent",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Start an interactive REPL session",
    )
    parser.add_argument(
        "--model",
        default="local",
        help="Model name or identifier",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API key for the model provider",
    )
    return parser.parse_args(argv)


async def run_agent(message: list[str], model: str, api_key: str) -> None:
    """Run the agent with the given message."""
    from R.A.I.N._tools import create_agent, shell, file_read, file_write

    agent = create_agent(
        tools=[shell, file_read, file_write],
        model=model,
        api_key=api_key,
    )
    result = await agent.ainvoke({"messages": message})
    print(result)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.interactive or not args.message:
        print("R.A.I.N.-tools interactive mode (stub)")
        return 0

    asyncio.run(run_agent(args.message, args.model, args.api_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
