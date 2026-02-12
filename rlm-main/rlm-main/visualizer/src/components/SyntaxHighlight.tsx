'use client';

import { useMemo } from 'react';

interface SyntaxHighlightProps {
  code: string;
  language?: 'python' | 'text';
}

// Simple Python syntax highlighting
function highlightPython(code: string): React.ReactNode[] {
  const keywords = [
    'def', 'class', 'if', 'elif', 'else', 'for', 'while', 'try', 'except', 
    'finally', 'with', 'as', 'import', 'from', 'return', 'yield', 'raise',
    'pass', 'break', 'continue', 'and', 'or', 'not', 'in', 'is', 'None',
    'True', 'False', 'lambda', 'async', 'await', 'global', 'nonlocal'
  ];
  
  const builtins = [
    'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set',
    'tuple', 'type', 'isinstance', 'enumerate', 'zip', 'map', 'filter',
    'sorted', 'reversed', 'sum', 'min', 'max', 'abs', 'open', 'input'
  ];
  
  const lines = code.split('\n');
  const result: React.ReactNode[] = [];
  
  lines.forEach((line, lineIdx) => {
    let remaining = line;
    const lineElements: React.ReactNode[] = [];
    let charIdx = 0;
    
    while (remaining.length > 0) {
      // Comments
      if (remaining.startsWith('#')) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-comment`} className="text-[oklch(0.55_0.05_260)]">
            {remaining}
          </span>
        );
        remaining = '';
        continue;
      }
      
      // Strings (single and double quotes, including f-strings)
      const stringMatch = remaining.match(/^(f?r?)(["'])(?:(?!\2)[^\\]|\\.)*\2/);
      if (stringMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-string`} className="text-[oklch(0.75_0.15_145)]">
            {stringMatch[0]}
          </span>
        );
        remaining = remaining.slice(stringMatch[0].length);
        charIdx += stringMatch[0].length;
        continue;
      }
      
      // Triple-quoted strings
      const tripleStringMatch = remaining.match(/^(["']{3})[\s\S]*?\1/);
      if (tripleStringMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-triplestring`} className="text-[oklch(0.75_0.15_145)]">
            {tripleStringMatch[0]}
          </span>
        );
        remaining = remaining.slice(tripleStringMatch[0].length);
        charIdx += tripleStringMatch[0].length;
        continue;
      }
      
      // Numbers
      const numberMatch = remaining.match(/^\b\d+\.?\d*\b/);
      if (numberMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-number`} className="text-[oklch(0.85_0.15_45)]">
            {numberMatch[0]}
          </span>
        );
        remaining = remaining.slice(numberMatch[0].length);
        charIdx += numberMatch[0].length;
        continue;
      }
      
      // Keywords
      const keywordMatch = remaining.match(new RegExp(`^\\b(${keywords.join('|')})\\b`));
      if (keywordMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-keyword`} className="text-[oklch(0.7_0.2_320)]">
            {keywordMatch[0]}
          </span>
        );
        remaining = remaining.slice(keywordMatch[0].length);
        charIdx += keywordMatch[0].length;
        continue;
      }
      
      // Builtins
      const builtinMatch = remaining.match(new RegExp(`^\\b(${builtins.join('|')})\\b`));
      if (builtinMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-builtin`} className="text-[oklch(0.8_0.15_195)]">
            {builtinMatch[0]}
          </span>
        );
        remaining = remaining.slice(builtinMatch[0].length);
        charIdx += builtinMatch[0].length;
        continue;
      }
      
      // Function definitions
      const funcMatch = remaining.match(/^(\w+)(?=\()/);
      if (funcMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-func`} className="text-[oklch(0.85_0.12_220)]">
            {funcMatch[0]}
          </span>
        );
        remaining = remaining.slice(funcMatch[0].length);
        charIdx += funcMatch[0].length;
        continue;
      }
      
      // Operators and punctuation
      const operatorMatch = remaining.match(/^[+\-*/%=<>!&|^~@:.,;()\[\]{}]+/);
      if (operatorMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-operator`} className="text-[oklch(0.7_0.1_260)]">
            {operatorMatch[0]}
          </span>
        );
        remaining = remaining.slice(operatorMatch[0].length);
        charIdx += operatorMatch[0].length;
        continue;
      }
      
      // Regular text/identifiers
      const textMatch = remaining.match(/^[^\s+\-*/%=<>!&|^~@:.,;()\[\]{}#"']+/);
      if (textMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-text`} className="text-foreground/90">
            {textMatch[0]}
          </span>
        );
        remaining = remaining.slice(textMatch[0].length);
        charIdx += textMatch[0].length;
        continue;
      }
      
      // Whitespace
      const wsMatch = remaining.match(/^\s+/);
      if (wsMatch) {
        lineElements.push(wsMatch[0]);
        remaining = remaining.slice(wsMatch[0].length);
        charIdx += wsMatch[0].length;
        continue;
      }
      
      // Fallback: consume one character
      lineElements.push(remaining[0]);
      remaining = remaining.slice(1);
      charIdx++;
    }
    
    result.push(
      <div key={`line-${lineIdx}`} className="whitespace-pre">
        {lineElements}
      </div>
    );
  });
  
  return result;
}

export function SyntaxHighlight({ code, language = 'python' }: SyntaxHighlightProps) {
  const highlighted = useMemo(() => {
    if (language === 'python') {
      return highlightPython(code);
    }
    return <span className="text-foreground/90">{code}</span>;
  }, [code, language]);
  
  return <>{highlighted}</>;
}

