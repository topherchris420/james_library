import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { RainService } from '../services/rain.service';

@Component({
  selector: 'app-top-nav',
  standalone: true,
  imports: [CommonModule, MatIconModule],
  template: `
    <div class="h-14 border-b border-rain-green/20 bg-rain-bg flex items-center justify-between px-6 select-none relative overflow-hidden">
      <!-- Scanning Line (Normal) -->
      @if (!rainService.isAlarmActive()) {
        <div class="absolute top-0 left-0 w-full h-[1px] bg-rain-green/50 animate-scan"></div>
      }

      <!-- Alarm Lines (Angry) -->
      @if (rainService.isAlarmActive()) {
        <div class="absolute top-0 left-0 w-1/2 h-[2px] bg-rain-red animate-alarm-left shadow-[0_0_10px_rgba(255,0,0,0.8)]"></div>
        <div class="absolute top-0 right-0 w-1/2 h-[2px] bg-rain-red animate-alarm-right shadow-[0_0_10px_rgba(255,0,0,0.8)]"></div>
        <div class="absolute inset-0 bg-rain-red/10 animate-pulse pointer-events-none"></div>
      }

      <!-- Logo Area -->
      <div class="flex items-center gap-4 z-10">
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 bg-rain-red animate-pulse"></div>
          <div class="w-2 h-2 bg-rain-green animate-pulse delay-75"></div>
          <div class="w-2 h-2 bg-rain-accent animate-pulse delay-150"></div>
          <span class="text-xl font-bold tracking-[0.2em] text-rain-green glitch-text" data-text="R.A.I.N.">R.A.I.N.</span>
        </div>
        <span class="text-[10px] text-rain-muted border-l border-rain-green/20 pl-4 tracking-[0.3em] uppercase">
          Classified // Level 5 Clearance
        </span>
      </div>

      <!-- Right Actions -->
      <div class="flex items-center gap-2 z-10">
        <div class="text-[10px] text-rain-green/50 font-mono mr-4 animate-pulse">
          SYS.STATUS: ONLINE
        </div>
        
        <button 
          class="h-8 px-3 flex items-center gap-2 text-rain-green/70 hover:text-rain-green hover:bg-rain-green/10 transition-all border border-transparent hover:border-rain-green/30 text-xs uppercase tracking-wider"
          title="Documentation">
          <mat-icon class="text-[16px]">help_outline</mat-icon>
          <span class="hidden sm:inline">Docs</span>
        </button>
      </div>
    </div>
  `,
  styles: [`
    @keyframes scan {
      0% { transform: translateX(-100%); }
      100% { transform: translateX(100%); }
    }
    .animate-scan {
      animation: scan 4s linear infinite;
    }
    @keyframes alarm-left {
      0% { transform: translateX(-100%); }
      50% { transform: translateX(100%); }
      100% { transform: translateX(-100%); }
    }
    @keyframes alarm-right {
      0% { transform: translateX(100%); }
      50% { transform: translateX(-100%); }
      100% { transform: translateX(100%); }
    }
    .animate-alarm-left {
      animation: alarm-left 0.5s linear infinite;
    }
    .animate-alarm-right {
      animation: alarm-right 0.5s linear infinite;
    }
    .glitch-text {
      position: relative;
    }
    .glitch-text::before,
    .glitch-text::after {
      content: attr(data-text);
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
    }
    .glitch-text::before {
      left: 2px;
      text-shadow: -1px 0 #ff00c1;
      clip: rect(44px, 450px, 56px, 0);
      animation: glitch-anim 5s infinite linear alternate-reverse;
    }
    .glitch-text::after {
      left: -2px;
      text-shadow: -1px 0 #00fff9;
      clip: rect(44px, 450px, 56px, 0);
      animation: glitch-anim2 5s infinite linear alternate-reverse;
    }
    @keyframes glitch-anim {
      0% { clip: rect(38px, 9999px, 14px, 0); }
      20% { clip: rect(6px, 9999px, 88px, 0); }
      40% { clip: rect(64px, 9999px, 12px, 0); }
      60% { clip: rect(42px, 9999px, 79px, 0); }
      80% { clip: rect(18px, 9999px, 54px, 0); }
      100% { clip: rect(95px, 9999px, 26px, 0); }
    }
    @keyframes glitch-anim2 {
      0% { clip: rect(21px, 9999px, 96px, 0); }
      20% { clip: rect(5px, 9999px, 4px, 0); }
      40% { clip: rect(88px, 9999px, 32px, 0); }
      60% { clip: rect(12px, 9999px, 64px, 0); }
      80% { clip: rect(56px, 9999px, 21px, 0); }
      100% { clip: rect(2px, 9999px, 85px, 0); }
    }
  `]
})
export class TopNavComponent {
  rainService = inject(RainService);
}
