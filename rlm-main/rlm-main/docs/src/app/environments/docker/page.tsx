import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function DockerPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4 flex items-center gap-3">
        DockerREPL
        <img 
          src="https://github.com/docker.png" 
          alt="Docker" 
          height="24" 
          className="inline-block"
          style={{ height: '24px', verticalAlign: 'middle' }}
        />
      </h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        <strong className="text-foreground">DockerREPL</strong> executes Python code in a <strong className="text-foreground">Docker container</strong> 
        running on the same host machine as the RLM process. Each code execution runs in an isolated container environment 
        with its own filesystem, network namespace, and process tree, providing better security and reproducibility than 
        LocalREPL. The container requests LM calls from the host&apos;s LM Handler when code executes <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">llm_query()</code>. 
        This environment is ideal for CI/CD pipelines, reproducible execution environments, and scenarios requiring stronger 
        isolation than LocalREPL while maintaining the convenience of local execution. For more information on Docker, see the{" "}
        <a href="https://docs.docker.com/" className="text-primary hover:underline font-medium">Docker documentation</a>.
      </p>

      <p className="text-muted-foreground mb-4">
        <strong>Prerequisite:</strong> Docker must be installed and running.
      </p>

      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="docker",
    environment_kwargs={
        "image": "python:3.11-slim",
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Arguments</h2>
      <Table 
        headers={["Argument", "Type", "Default", "Description"]}
        rows={[
          [<code key="1">image</code>, <code key="2">str</code>, <code key="3">&quot;python:3.11-slim&quot;</code>, "Docker image to use"],
          [<code key="4">setup_code</code>, <code key="5">str</code>, <code key="6">None</code>, "Code to run at initialization"],
          [<code key="7">context_payload</code>, <code key="8">str | dict | list</code>, "Auto", "Initial context (set by RLM)"],
          [<code key="9">lm_handler_address</code>, <code key="10">tuple</code>, "Auto", "Socket address (set by RLM)"],
        ]}
      />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">How It Works</h2>
      <ol className="list-decimal list-inside text-muted-foreground space-y-1 mb-6">
        <li>Starts Docker container with volume mount to temp directory</li>
        <li>Installs <code>dill</code> and <code>requests</code> in container</li>
        <li>Host runs HTTP proxy server on random port</li>
        <li>Container calls proxy via <code>host.docker.internal</code></li>
        <li>Proxy forwards <code>llm_query()</code> to LM Handler via socket</li>
        <li>State persisted via <code>dill</code> to <code>/workspace/state.dill</code></li>
      </ol>

      <pre className="text-sm">{`┌────────────────────────────────────────┐
│ Host                                   │
│  ┌────────────┐ Socket ┌────────────┐ │
│  │ HTTP Proxy │◄──────►│ LM Handler │ │
│  └─────┬──────┘        └────────────┘ │
└────────┼───────────────────────────────┘
         │ HTTP
┌────────┼───────────────────────────────┐
│ Docker │ Container                     │
│  ┌─────▼──────┐                        │
│  │   Python   │ llm_query() → proxy    │
│  │   exec()   │                        │
│  └────────────┘                        │
└────────────────────────────────────────┘`}</pre>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Custom Image</h2>
      <p className="text-muted-foreground mb-4">
        You can use your own custom Docker images or update the given image. Pre-install dependencies:
      </p>
      <CodeBlock language="bash" code={`FROM python:3.11-slim
RUN pip install numpy pandas dill requests`} />
      <CodeBlock code={`environment_kwargs={"image": "my-rlm-image"}`} />
    </div>
  );
}

