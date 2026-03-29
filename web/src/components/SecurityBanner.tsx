import { ArrowRight, ShieldCheck } from 'lucide-react';

export default function SecurityBanner() {
  return (
    <div className="w-full bg-emerald-950/30 border-b border-emerald-900/50 backdrop-blur-md relative z-[100] animate-fade-in">
      <div className="max-w-7xl mx-auto px-4 py-2.5 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-center gap-2 text-sm">
        <div className="flex items-center gap-2 text-zinc-200">
          <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
          <span className="text-center sm:text-left">
            <span className="font-semibold text-white tracking-wide">100% Open Source.</span>{' '}
            Local-by-default. Sandboxed execution.
          </span>
        </div>

        <a
          href="https://github.com/topherchris420/james_library/blob/main/SECURITY.md"
          target="_blank"
          rel="noopener noreferrer"
          className="group flex items-center gap-1 text-emerald-400 hover:text-emerald-300 font-medium transition-colors"
        >
          Read our Security Architecture on GitHub
          <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-1" />
        </a>
      </div>
    </div>
  );
}
