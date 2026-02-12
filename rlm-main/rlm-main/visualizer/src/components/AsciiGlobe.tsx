'use client';

import { useEffect, useState } from 'react';

// RLM Architecture ASCII art inspired by the diagram
const RLM_SIMPLE = `
                    ╔══════════════════════════════════════════╗
  ┌──────────┐      ║            RLM (depth=0)                 ║      ┌──────────┐
  │  Prompt  │      ║  ┌────────────────────────────────────┐  ║      │  Answer  │
  │──────────│ ───► ║  │        Language Model (LM)         │  ║ ───► │──────────│
  │ context  │      ║  └─────────────────┬──────────────────┘  ║      │  FINAL() │
  └──────────┘      ║                   ↓ ↑                    ║      └──────────┘
                    ║  ┌─────────────────▼──────────────────┐  ║
                    ║  │       Environment (REPL)           │  ║
                    ║  │     context · llm_query()          │  ║
                    ║  └──────────┬────────────┬────────────┘  ║
                    ╚═════════════│════════════│═══════════════╝
                                  │            │
                         ┌────────▼────┐  ┌────▼────────┐
                         │ llm_query() │  │ llm_query() │
                         └────────┬────┘  └────┬────────┘
                                  │            │
                         ╔════════▼════╗  ╔════▼════════╗
                         ║ RLM (d=1)   ║  ║ RLM (d=1)   ║
                         ║  LM ↔ REPL  ║  ║  LM ↔ REPL  ║
                         ╚═════════════╝  ╚═════════════╝
`;

export function AsciiRLM() {
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setPulse(p => (p + 1) % 4);
    }, 600);
    return () => clearInterval(interval);
  }, []);

  // Colorize the ASCII art
  const colorize = (text: string) => {
    return text.split('\n').map((line, lineIdx) => (
      <div key={lineIdx} className="whitespace-pre">
        {line.split('').map((char, charIdx) => {
          const key = `${lineIdx}-${charIdx}`;
          
          // Box drawing characters - dim
          if ('┌┐└┘├┤┬┴┼─│╔╗╚╝║═'.includes(char)) {
            return <span key={key} className="text-muted-foreground/50">{char}</span>;
          }
          // Arrows - primary color
          if ('▼▲↓↑→←'.includes(char)) {
            const isPulsing = (lineIdx + charIdx + pulse) % 4 === 0;
            return (
              <span 
                key={key} 
                className={isPulsing ? 'text-primary' : 'text-primary/60'}
              >
                {char}
              </span>
            );
          }
          // Keywords
          if (line.includes('RLM') && char !== ' ') {
            if ('RLM'.includes(char)) {
              return <span key={key} className="text-primary font-bold">{char}</span>;
            }
          }
          if (line.includes('Prompt') || line.includes('Response') || line.includes('Answer')) {
            if (!'[]│─'.includes(char) && char !== ' ') {
              return <span key={key} className="text-amber-600 dark:text-amber-400">{char}</span>;
            }
          }
          if (line.includes('Language Model') || line.includes('LM')) {
            if (!'[]│─┌┐└┘'.includes(char) && char !== ' ') {
              return <span key={key} className="text-sky-600 dark:text-sky-400">{char}</span>;
            }
          }
          if (line.includes('REPL') || line.includes('Environment') || line.includes('context') || line.includes('llm_query')) {
            if (!'[]│─┌┐└┘'.includes(char) && char !== ' ') {
              return <span key={key} className="text-emerald-600 dark:text-emerald-400">{char}</span>;
            }
          }
          if (line.includes('depth=')) {
            if (!'()'.includes(char) && char !== ' ') {
              return <span key={key} className="text-muted-foreground">{char}</span>;
            }
          }
          // Default
          return <span key={key} className="text-muted-foreground/70">{char}</span>;
        })}
      </div>
    ));
  };

  return (
    <div className="font-mono text-[10px] leading-[1.3] select-none">
      <pre>{colorize(RLM_SIMPLE)}</pre>
    </div>
  );
}

// Compact inline diagram for header
export function AsciiRLMInline() {
  return (
    <div className="font-mono text-[9px] leading-tight select-none text-muted-foreground">
      <span className="text-primary">Prompt</span>
      <span> → </span>
      <span className="text-emerald-600 dark:text-emerald-400">[LM ↔ REPL]</span>
      <span> → </span>
      <span className="text-amber-600 dark:text-amber-400">Answer</span>
    </div>
  );
}
