"""
Example: Using llm_query() from within a Local REPL environment.

This demonstrates the LM Handler + LocalREPL integration where code
running in the REPL can query the LLM via socket connection.
"""

import os

from dotenv import load_dotenv

from rlm.clients.portkey import PortkeyClient
from rlm.core.lm_handler import LMHandler
from rlm.environments.local_repl import LocalREPL

load_dotenv()

setup_code = """
secret = "1424424"
"""

context_payload = """
This is a test context. It should print out, revealing the magic number to be 4.
"""

code = """
response = llm_query("What is 2 + 2? Reply with just the number.")
print(response)
print(type(response))
print(context)
print("Secret from setup code: ", secret)
"""


def main():
    api_key = os.environ.get("PORTKEY_API_KEY")
    if not api_key:
        print("Error: PORTKEY_API_KEY not set")
        return
    print(f"PORTKEY_API_KEY: {api_key}")

    client = PortkeyClient(api_key=api_key, model_name="@openai/gpt-5-nano")
    print("Created Portkey client with model: @openai/gpt-5-nano")

    # Start LM Handler
    with LMHandler(client=client) as handler:
        print(f"LM Handler started at {handler.address}")

        # Create REPL with handler connection
        with LocalREPL(
            lm_handler_address=handler.address,
            context_payload=context_payload,
            setup_code=setup_code,
        ) as repl:
            print("LocalREPL created, connected to handler\n")

            # Run code that uses llm_query
            print(f"Executing: {code}")

            result = repl.execute_code(code)

            print(f"stdout: {result.stdout!r}")
            print(f"stderr: {result.stderr!r}")
            print(f"response variable: {repl.locals.get('response')!r}")
            print(f"locals: {repl.locals!r}")
            print(f"execution time: {result.execution_time:.3f}s")


if __name__ == "__main__":
    main()
