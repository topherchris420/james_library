import { CodeBlock } from "@/components/CodeBlock";

export default function TrajectoriesPage() {
  return (
    <div className="max-w-4xl">
      <h1 className="text-3xl font-bold mb-4">Visualizing RLM Trajectories</h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        RLM provides built-in logging capabilities to save execution trajectories, enabling you to 
        analyze how the LM decomposes tasks, executes code, and makes recursive calls.
      </p>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Setting Up the Logger</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          To log RLM execution trajectories, initialize an <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">RLMLogger</code> 
          and pass it to the RLM constructor:
        </p>

        <CodeBlock code={`from rlm import RLM
from rlm.logger import RLMLogger

# Initialize logger with output directory
logger = RLMLogger(log_dir="./logs")

# Pass logger to RLM
rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    logger=logger,  # Enable trajectory logging
    verbose=False,  # print to logs
)

# Run completion - trajectories are automatically saved
result = rlm.completion("Your prompt here")`} />
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Accessing Logged Trajectories</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          Trajectories are saved as JSON-lines files in the specified log directory. Each line contains 
          a complete snapshot of one RLM iteration, including:
        </p>

        <ul className="list-disc list-inside text-muted-foreground space-y-2 mb-6 ml-2">
          <li><strong className="text-foreground">LM prompts and responses</strong> — All prompts sent to the LM and their completions</li>
          <li><strong className="text-foreground">Generated code</strong> — Python code written by the LM</li>
          <li><strong className="text-foreground">Code execution results</strong> — stdout, stderr, and return values</li>
          <li><strong className="text-foreground">Sub-LM calls</strong> — All <code className="px-1 py-0.5 rounded bg-muted text-foreground text-xs font-semibold">llm_query()</code> invocations and their results</li>
          <li><strong className="text-foreground">Metadata</strong> — Timestamps, model names, token usage, execution times</li>
        </ul>

        <CodeBlock code={`import json

# Read trajectory file
with open("./logs/trajectory_20250101_123456.jsonl", "r") as f:
    for line in f:
        iteration = json.loads(line)
        print(f"Iteration {iteration['iteration']}")
        print(f"Prompt: {iteration['prompt'][:100]}...")
        print(f"Code: {iteration.get('code', 'N/A')}")
        print(f"Result: {iteration.get('result', {}).get('stdout', 'N/A')}")
        print("---")`} />
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Visualization Example</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          The logged trajectories can be visualized to understand the RLM&apos;s decision-making process. 
          Below is an example visualization showing how the LM decomposes a complex task:
        </p>

        <div className="bg-gradient-to-br from-slate-50 to-blue-50 border-2 border-slate-200 rounded-xl p-6 mb-6">
          <img 
            src="/rlm/visualizer.png" 
            alt="RLM Trajectory Visualization" 
            className="rounded-lg shadow-sm w-full h-auto"
          />
        </div>

        <p className="text-muted-foreground leading-relaxed">
          This visualization shows the recursive structure of RLM execution, with each node representing 
          an LM call and edges showing the flow of context and sub-problem decomposition. The logger 
          captures all this information, enabling detailed analysis of the RLM&apos;s reasoning process.
        </p>
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Log File Structure</h2>
        
        <p className="text-muted-foreground mb-4 leading-relaxed">
          Each log file contains one JSON object per line (JSON-lines format). The structure includes:
        </p>

        <CodeBlock code={`{
  "iteration": 0,
  "timestamp": "2025-01-01T12:34:56.789Z",
  "prompt": "...",
  "response": "...",
  "code": "...",
  "result": {
    "stdout": "...",
    "stderr": "",
    "return_value": null
  },
  "sub_calls": [
    {
      "prompt": "...",
      "response": "...",
      "model": "gpt-5-mini"
    }
  ],
  "usage": {
    "input_tokens": 150,
    "output_tokens": 75
  },
  "execution_time": 1.23
}`} />
      </div>
    </div>
  );
}

