import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { RainService, Artifact } from '../services/rain.service';

@Component({
  selector: 'app-artifact-bar',
  standalone: true,
  imports: [CommonModule, MatIconModule],
  template: `
    @if (artifact(); as art) {
      <div class="h-14 border-t border-rain-green/20 bg-rain-bg flex items-center justify-between px-6 animate-slide-up group relative overflow-hidden">
        <!-- Scanning Line -->
        <div class="absolute top-0 left-0 w-full h-[1px] bg-rain-green/30"></div>

        <div class="flex items-center gap-4 z-10">
          <span class="text-[10px] uppercase tracking-[0.2em] text-rain-green border border-rain-green/30 px-2 py-1 bg-rain-green/5">
            {{ art.type }}
          </span>
          <span class="text-sm font-mono text-white italic tracking-wide">
            "{{ art.content }}"
          </span>
        </div>
        
        <div class="flex items-center gap-4 z-10">
          <div class="text-[10px] text-rain-green/50 font-mono tracking-widest">
            SESSION ID: {{ sessionId }}
          </div>
          <button 
            (click)="rotate()"
            class="text-rain-green/50 hover:text-rain-green opacity-0 group-hover:opacity-100 transition-all transform hover:rotate-180 duration-500"
            title="Rotate Artifact">
            <mat-icon class="text-sm">refresh</mat-icon>
          </button>
        </div>
      </div>
    }
  `,
  styles: [`
    .animate-slide-up {
      animation: slideUp 0.3s ease-out forwards;
    }
    @keyframes slideUp {
      from { transform: translateY(100%); }
      to { transform: translateY(0); }
    }
  `]
})
export class ArtifactBarComponent {
  rainService = inject(RainService);
  artifact = this.rainService.artifact;
  sessionId = Math.random().toString(36).substring(7).toUpperCase();

  rotate() {
    this.rainService.rotateArtifact();
  }
}
