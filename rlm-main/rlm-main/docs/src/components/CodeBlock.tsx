"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Check, Copy } from "lucide-react";

interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
}

function highlightBash(code: string): string {
  // Escape HTML
  let result = code
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Highlight comments - simple and safe
  return result.replace(/#.*$/gm, (match) => {
    return '<span class="token-comment">' + match + '</span>';
  });
}

function highlightPython(code: string): string {
  // Escape HTML first
  let result = code
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Use a simple approach: process in order and use unique markers
  // to avoid matching our own HTML
  
  // Step 1: Protect strings by replacing with markers
  const stringMarkers: string[] = [];
  result = result.replace(/(["'])((?:\\.|(?!\1)[^\\])*?)\1/g, (match) => {
    const marker = `__STRING_MARKER_${stringMarkers.length}__`;
    stringMarkers.push(match);
    return marker;
  });
  
  // Step 2: Highlight keywords
  const keywords = /\b(from|import|def|class|return|if|else|elif|for|while|with|as|try|except|finally|raise|yield|lambda|and|or|not|in|is|None|True|False|async|await)\b/g;
  result = result.replace(keywords, '<span class="token-keyword">$&</span>');
  
  // Step 3: Highlight functions
  result = result.replace(/\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\()/g, '<span class="token-function">$1</span>');
  
  // Step 4: Highlight numbers
  result = result.replace(/\b\d+\.?\d*\b/g, '<span class="token-number">$&</span>');
  
  // Step 5: Highlight comments
  result = result.replace(/#.*$/gm, '<span class="token-comment">$&</span>');
  
  // Step 6: Restore strings with highlighting
  stringMarkers.forEach((str, i) => {
    result = result.replace(`__STRING_MARKER_${i}__`, '<span class="token-string">' + str + '</span>');
  });
  
  return result;
}

export function CodeBlock({ code, language = "python", filename }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const highlighted = language === "bash" ? highlightBash(code) : highlightPython(code);

  return (
    <div className="relative group my-6">
      {filename && (
        <div className="bg-muted px-4 py-2.5 text-sm text-muted-foreground border border-b-0 border-border rounded-t-lg font-mono font-medium">
          {filename}
        </div>
      )}
      <pre className={cn("relative shadow-sm overflow-x-auto", filename && "rounded-t-none rounded-b-lg", !filename && "rounded-lg")}>
        <button
          onClick={handleCopy}
          className="absolute top-3 right-3 p-2 rounded-md bg-background/90 hover:bg-background border border-border shadow-sm opacity-0 group-hover:opacity-100 transition-all hover:scale-105 z-10"
          aria-label="Copy code"
        >
          {copied ? (
            <Check className="h-4 w-4 text-green-600" />
          ) : (
            <Copy className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          )}
        </button>
        <code 
          className="block font-mono text-sm leading-relaxed whitespace-pre" 
          dangerouslySetInnerHTML={{ __html: highlighted }} 
        />
      </pre>
    </div>
  );
}
