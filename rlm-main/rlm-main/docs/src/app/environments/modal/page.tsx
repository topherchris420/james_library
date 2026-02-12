import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function ModalPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4 flex items-center gap-3">
        ModalREPL
        <img 
          src="https://github.com/modal-labs.png" 
          alt="Modal" 
          height="24" 
          className="inline-block"
          style={{ height: '24px', verticalAlign: 'middle' }}
        />
      </h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        <strong className="text-foreground">ModalREPL</strong> executes Python code in <strong className="text-foreground">Modal cloud sandboxes</strong>, 
        which are ephemeral cloud VMs that run completely isolated from the host machine. Each sandbox is a fresh, 
        isolated environment with its own filesystem, network, and compute resources, providing the highest level of 
        security and isolation available in RLM. The sandbox requests LM calls from the host&apos;s LM Handler when code 
        executes <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">llm_query()</code>. 
        This environment is production-ready and essential for executing untrusted LM-generated code or handling sensitive data. 
        For more information on Modal sandboxes, see the{" "}
        <a href="https://modal.com/docs/guide/sandbox" className="text-primary hover:underline font-medium">Modal sandboxes documentation</a>.
      </p>

      <p className="text-muted-foreground mb-2"><strong>Prerequisites:</strong></p>
      <CodeBlock language="bash" code={`uv pip install -e . --extra modal
# Or with regular pip:
# pip install -e ".[modal]"

modal setup  # Authenticate`} />

      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="modal",
    environment_kwargs={
        "app_name": "my-rlm-app",
        "timeout": 600,
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Arguments</h2>
      <Table 
        headers={["Argument", "Type", "Default", "Description"]}
        rows={[
          [<code key="1">app_name</code>, <code key="2">str</code>, <code key="3">&quot;rlm-sandbox&quot;</code>, "Modal app name"],
          [<code key="4">timeout</code>, <code key="5">int</code>, <code key="6">600</code>, "Sandbox timeout in seconds"],
          [<code key="7">image</code>, <code key="8">modal.Image</code>, "Auto", "Custom Modal image"],
          [<code key="9">setup_code</code>, <code key="10">str</code>, <code key="11">None</code>, "Code to run at initialization"],
          [<code key="12">context_payload</code>, <code key="13">str | dict | list</code>, "Auto", "Initial context (set by RLM)"],
          [<code key="14">lm_handler_address</code>, <code key="15">tuple</code>, "Auto", "Socket address (set by RLM)"],
        ]}
      />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">How It Works</h2>
      <p className="text-muted-foreground mb-4">
        Modal sandboxes can&apos;t connect directly to the host. Uses HTTP broker pattern:
      </p>
      <ol className="list-decimal list-inside text-muted-foreground space-y-1 mb-6">
        <li>Sandbox starts Flask broker server on port 8080</li>
        <li>Port exposed via Modal&apos;s <code>encrypted_ports</code> tunnel</li>
        <li><code>llm_query()</code> POSTs to local broker, blocks waiting</li>
        <li>Host polls <code>{"{tunnel}/pending"}</code> every 100ms</li>
        <li>Host forwards requests to LM Handler, POSTs responses back</li>
        <li>Broker unblocks and returns response</li>
      </ol>

      <pre className="text-sm">{`Host polls /pending ────────────────┐
                                    │
┌───────────────────────────────────┼──┐
│ Modal Sandbox                     ▼  │
│  ┌──────────────┐   ┌──────────────┐ │
│  │ Broker Flask │◄─►│ Code Exec    │ │
│  │  /enqueue    │   │ llm_query()  │ │
│  │  /pending    │   └──────────────┘ │
│  │  /respond    │                    │
│  └──────────────┘                    │
└──────────────────────────────────────┘`}</pre>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Custom Image</h2>
      <p className="text-muted-foreground mb-4">
        You can use your own custom Modal images or update the given image:
      </p>
      <CodeBlock code={`import modal

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "numpy", "pandas", "dill", "requests", "flask"
)

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="modal",
    environment_kwargs={"image": image},
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Default Image</h2>
      <p className="text-muted-foreground">
        Includes: <code>numpy</code>, <code>pandas</code>, <code>scipy</code>, <code>sympy</code>, <code>requests</code>, <code>httpx</code>, <code>flask</code>, <code>pyyaml</code>, <code>tqdm</code>, <code>dill</code>
      </p>
    </div>
  );
}

