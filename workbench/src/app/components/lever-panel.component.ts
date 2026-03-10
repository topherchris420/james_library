import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { RainService } from '../services/rain.service';
import { unparse } from 'papaparse';

@Component({
  selector: 'app-lever-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  template: `
    <div class="h-full flex flex-col p-6 border-l border-rain-green/20 bg-rain-bg relative overflow-hidden">
      <!-- Corner Accents -->
      <div class="absolute top-0 right-0 w-4 h-4 border-t border-r border-rain-green/50"></div>
      <div class="absolute bottom-0 left-0 w-4 h-4 border-b border-l border-rain-green/50"></div>
      
      <!-- Scanline -->
      <div class="absolute top-0 left-0 w-full h-[1px] bg-rain-green/50 animate-scan pointer-events-none"></div>

      <div class="flex items-center justify-between mb-6 border-b border-rain-green/20 pb-2">
        <h2 class="text-xs font-bold uppercase tracking-[0.2em] text-rain-red flex items-center gap-2 animate-pulse">
          <mat-icon class="text-sm">warning</mat-icon>
          // SELF-DESTRUCT IN {{ (rainService.logDestructTime().getTime() - now()) / 1000 | number:'1.0-0' }}S
        </h2>
      </div>

      <div class="flex-1 overflow-y-auto space-y-6 custom-scrollbar">
        
        <!-- Login Section -->
        <div class="space-y-4">
          <div class="flex gap-4">
            <div class="flex-1 space-y-1">
              <label class="text-[10px] uppercase text-rain-muted tracking-wider">Username</label>
              <input 
                type="text" 
                [(ngModel)]="username"
                class="w-full bg-rain-panel border border-rain-green/20 p-2 text-xs text-rain-green focus:border-rain-green focus:bg-rain-green/5 focus:outline-none font-mono placeholder-rain-green/20"
                placeholder="AGENT.ID" />
            </div>
            <div class="flex-1 space-y-1">
              <label class="text-[10px] uppercase text-rain-muted tracking-wider">Password</label>
              <input 
                type="password" 
                [(ngModel)]="password"
                class="w-full bg-rain-panel border border-rain-green/20 p-2 text-xs text-rain-green focus:border-rain-green focus:bg-rain-green/5 focus:outline-none font-mono placeholder-rain-green/20"
                placeholder="******" />
            </div>
            <div class="flex items-end">
              <button class="bg-rain-green/10 border border-rain-green text-rain-green px-4 py-2 text-xs font-bold uppercase tracking-wider hover:bg-rain-green hover:text-black transition-all h-[34px]">
                Login
              </button>
            </div>
          </div>

          <div class="flex justify-center">
            <button class="text-[10px] uppercase tracking-widest text-rain-muted hover:text-rain-green transition-colors flex items-center gap-2 border-b border-transparent hover:border-rain-green/50 pb-1">
              <mat-icon class="text-[14px]">security</mat-icon>
              Authenticate via Google Protocol
            </button>
          </div>
        </div>

        <div class="h-px bg-rain-green/10 w-full"></div>

        <!-- Export Section -->
        <div class="space-y-2">
          <label class="text-[10px] uppercase text-rain-muted block tracking-wider">Data Exfiltration</label>
          <div class="grid grid-cols-3 gap-4">
            <button 
              (click)="exportData('json')"
              class="flex items-center justify-center gap-2 border border-rain-green/30 bg-rain-green/5 py-2 text-[10px] uppercase tracking-wider text-rain-green hover:bg-rain-green hover:text-black transition-all group">
              <mat-icon class="text-[14px] group-hover:animate-bounce">data_object</mat-icon>
              JSON
            </button>
            <button 
              (click)="exportData('csv')"
              class="flex items-center justify-center gap-2 border border-rain-green/30 bg-rain-green/5 py-2 text-[10px] uppercase tracking-wider text-rain-green hover:bg-rain-green hover:text-black transition-all group">
              <mat-icon class="text-[14px] group-hover:animate-bounce">grid_on</mat-icon>
              CSV
            </button>
            <button 
              (click)="exportData('clipboard')"
              class="flex items-center justify-center gap-2 border border-rain-green/30 bg-rain-green/5 py-2 text-[10px] uppercase tracking-wider text-rain-green hover:bg-rain-green hover:text-black transition-all group">
              <mat-icon class="text-[14px] group-hover:animate-bounce">content_copy</mat-icon>
              Clipboard
            </button>
          </div>
        </div>

        <div class="h-px bg-rain-green/10 w-full"></div>

        <!-- System Logs -->
        <div class="flex-1 flex flex-col min-h-0">
          <div class="flex items-center justify-between mb-2">
            <label class="text-[10px] uppercase text-rain-muted block tracking-wider">System Logs</label>
          </div>
          <div class="flex-1 bg-black border border-rain-green/20 p-3 overflow-y-auto font-mono text-[10px] text-rain-green/80 custom-scrollbar shadow-inner min-h-[200px]">
            @for (log of rainService.logs(); track log.timestamp) {
              <div class="mb-1 border-l border-rain-green/20 pl-2 hover:bg-rain-green/5 transition-colors">
                <span class="text-rain-muted">[{{ log.timestamp | date:'HH:mm:ss' }}]</span>
                <span class="ml-2">{{ log.message }}</span>
              </div>
            }
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .custom-scrollbar::-webkit-scrollbar {
      width: 4px;
    }
    .custom-scrollbar::-webkit-scrollbar-track {
      background: rgba(255, 255, 255, 0.05);
    }
    .custom-scrollbar::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.2);
    }
    .animate-scan {
      animation: scan 4s linear infinite;
    }
    @keyframes scan {
      0% { transform: translateY(0); opacity: 0; }
      10% { opacity: 1; }
      90% { opacity: 1; }
      100% { transform: translateY(500px); opacity: 0; }
    }
  `]
})
export class LeverPanelComponent {
  rainService = inject(RainService);
  now = signal(Date.now());
  username = signal('');
  password = signal('');

  constructor() {
    setInterval(() => this.now.set(Date.now()), 1000);
    // Reset timer on load
    this.rainService.logDestructTime.set(new Date(Date.now() + 5 * 60000));
  }

  exportData(format: 'json' | 'csv' | 'clipboard') {
    const data = {
      tensions: this.rainService.tensions(),
      levers: this.rainService.levers(),
      input: this.rainService.inputState(),
      logs: this.rainService.logs()
    };

    if (format === 'clipboard') {
      navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      this.rainService.addLog('DATA EXFILTRATION: CLIPBOARD COPY SUCCESSFUL');
      return;
    }

    if (format === 'csv') {
      const csvData = this.rainService.levers().map(l => ({
        ID: l.id,
        Owner: l.owner,
        Description: l.description,
        Metric: l.metric,
        Start: l.horizonStart,
        End: l.horizonEnd,
        Response: l.response || 'PENDING'
      }));
      
      const csvContent = unparse(csvData);
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      this.downloadBlob(blob, 'rain-session-exfil.csv');
      this.rainService.addLog('DATA EXFILTRATION: CSV DOWNLOAD INITIATED');
      return;
    }

    // JSON Default
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    this.downloadBlob(blob, 'rain-session-exfil.json');
    this.rainService.addLog('DATA EXFILTRATION: JSON DOWNLOAD INITIATED');
  }

  private downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }
}
