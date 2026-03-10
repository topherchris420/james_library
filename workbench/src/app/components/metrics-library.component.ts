import { Component, inject, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RainService } from '../services/rain.service';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-metrics-library',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  template: `
    @if (isOpen()) {
      <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 flex items-center justify-center p-4" (click)="close()">
        <div class="bg-rain-bg border border-rain-green w-full max-w-md h-[60vh] flex flex-col shadow-2xl shadow-rain-green/10" (click)="$event.stopPropagation()">
          
          <div class="p-4 border-b border-white/10 flex items-center justify-between bg-rain-panel">
            <h3 class="text-rain-green text-xs font-bold uppercase tracking-widest">
              // Metrics Library
            </h3>
            <button (click)="close()" class="text-rain-muted hover:text-white">
              <mat-icon>close</mat-icon>
            </button>
          </div>

          <div class="p-4 border-b border-white/10">
            <input 
              [(ngModel)]="searchQuery"
              type="text" 
              class="w-full bg-rain-bg border border-white/10 p-2 text-sm text-white focus:border-rain-green focus:outline-none"
              placeholder="Search metrics..."
              autofocus />
          </div>

          <div class="flex-1 overflow-y-auto p-2 custom-scrollbar">
            @for (metric of filteredMetrics(); track metric) {
              <button 
                (click)="select(metric)"
                class="w-full text-left p-3 hover:bg-white/5 border-b border-white/5 text-sm text-rain-text transition-colors group flex items-center justify-between">
                <span>{{ metric }}</span>
                <mat-icon class="text-[16px] opacity-0 group-hover:opacity-100 text-rain-green">add</mat-icon>
              </button>
            }
          </div>

        </div>
      </div>
    }
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
  `]
})
export class MetricsLibraryComponent {
  rainService = inject(RainService);
  isOpen = computed(() => !!this.rainService.showMetricsLibrary());
  
  searchQuery = '';
  
  allMetrics = [
    'Time-to-decision',
    'Trust delta',
    'Defect rate',
    'Displacement index',
    'HHI',
    'Consent coverage',
    'Audit pass rate',
    'Burn multiple',
    'CAC payback',
    'NPS',
    'Employee eNPS',
    'Cycle time',
    'Lead time',
    'Change failure rate',
    'MTTR'
  ];

  filteredMetrics = computed(() => {
    const q = this.searchQuery.toLowerCase();
    return this.allMetrics.filter(m => m.toLowerCase().includes(q));
  });

  close() {
    this.rainService.closeMetricsLibrary();
  }

  select(metric: string) {
    this.rainService.selectMetric(metric);
  }
}
