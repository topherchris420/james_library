import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function LocalPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4">LocalREPL</h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        <strong className="text-foreground">LocalREPL</strong> is the default execution environment for RLM. 
        It runs Python code in the <strong className="text-foreground">same process</strong> as the RLM host application, 
        using Python&apos;s built-in <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">exec()</code> function 
        with a sandboxed namespace. The REPL shares the same virtual environment and memory space as the host process, 
        but restricts access to dangerous builtins like <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">eval</code>, 
        <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">exec</code>, and 
        <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">compile</code>. 
        This provides fast execution with minimal overhead, making it ideal for development and trusted code execution, 
        but offers no process-level isolation from the host system.
      </p>

      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="local",  # Default
    environment_kwargs={
        "setup_code": "import json",  # Optional
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Arguments</h2>
      <Table 
        headers={["Argument", "Type", "Default", "Description"]}
        rows={[
          [<code key="1">setup_code</code>, <code key="2">str</code>, <code key="3">None</code>, "Code to run at initialization"],
          [<code key="4">context_payload</code>, <code key="5">str | dict | list</code>, "Auto", "Initial context (set by RLM)"],
          [<code key="6">lm_handler_address</code>, <code key="7">tuple</code>, "Auto", "Socket address (set by RLM)"],
        ]}
      />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">How It Works</h2>
      <ol className="list-decimal list-inside text-muted-foreground space-y-1">
        <li>Creates sandboxed <code>globals</code> with restricted <code>__builtins__</code></li>
        <li>Injects <code>context</code>, <code>llm_query()</code>, <code>llm_query_batched()</code>, <code>FINAL_VAR()</code></li>
        <li>Executes each code block via <code>exec()</code></li>
        <li><code>llm_query()</code> sends TCP requests to LM Handler</li>
        <li>Variables persist across code blocks in <code>locals</code></li>
      </ol>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Sandboxed Builtins</h2>
      <p className="text-muted-foreground mb-2">
        <strong>Allowed:</strong> <code>print</code>, <code>len</code>, <code>range</code>, <code>str</code>, <code>int</code>, <code>float</code>, <code>list</code>, <code>dict</code>, <code>set</code>, <code>tuple</code>, <code>open</code>, <code>min</code>, <code>max</code>, <code>sum</code>, <code>sorted</code>, <code>enumerate</code>, <code>zip</code>, <code>map</code>, <code>filter</code>, standard exceptions
      </p>
      <p className="text-muted-foreground">
        <strong>Blocked:</strong> <code>eval</code>, <code>exec</code>, <code>compile</code>, <code>input</code>, <code>globals</code>, <code>locals</code>
      </p>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Limitations</h2>
      <ul className="list-disc list-inside text-muted-foreground space-y-1">
        <li>Shares process memory with host</li>
        <li>No network isolation</li>
        <li>Dependencies must be installed in host virtualenv</li>
      </ul>
    </div>
  );
}

