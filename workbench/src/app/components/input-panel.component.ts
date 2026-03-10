import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RainService, Horizon, TemplateMode } from '../services/rain.service';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-input-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  template: `
    <div class="h-full flex flex-col p-6 border-r border-rain-green/20 bg-rain-bg relative">
      <!-- Corner Accents -->
      <div class="absolute top-0 left-0 w-4 h-4 border-t border-l border-rain-green/50"></div>
      <div class="absolute bottom-0 right-0 w-4 h-4 border-b border-r border-rain-green/50"></div>

      <div class="mb-6 border-b border-rain-green/20 pb-2">
        <h2 class="text-xs font-bold uppercase tracking-[0.2em] text-rain-green flex items-center gap-2 mb-1">
          <mat-icon class="text-sm">input</mat-icon>
          01 // SUBJECT
        </h2>
        <input 
          type="text" 
          class="w-full bg-transparent text-[10px] text-rain-muted font-mono uppercase tracking-widest focus:outline-none focus:text-rain-green placeholder-rain-muted/30"
          placeholder="ENTER SUBJECT NUMBER..." />
      </div>
      
      <div class="flex-1 overflow-y-auto space-y-6 pr-2 custom-scrollbar">
        
        <!-- Template Toggle -->
        <div class="flex border border-rain-green/30 bg-rain-green/5">
          @for (mode of modes; track mode) {
            <button 
              (click)="setMode(mode)"
              [class.bg-rain-green]="inputState().template === mode"
              [class.text-black]="inputState().template === mode"
              [class.text-rain-green]="inputState().template !== mode"
              class="flex-1 py-2 text-[10px] uppercase font-bold tracking-wider transition-all hover:bg-rain-green/20">
              {{ mode === 'Standard' ? 'A' : mode === 'Rapid Triage' ? 'B' : 'C' }}
            </button>
          }
        </div>
        <div class="text-[10px] text-rain-green/70 text-right uppercase tracking-widest font-mono">
          >> MODE: {{ inputState().template }}
        </div>

        <!-- Context -->
        <div class="space-y-2 group">
          <label class="text-[10px] uppercase text-rain-muted tracking-wider group-focus-within:text-rain-green transition-colors">Context</label>
          <textarea 
            [ngModel]="inputState().context"
            (ngModelChange)="update('context', $event)"
            rows="4"
            class="w-full bg-rain-panel border border-rain-green/20 p-3 text-sm text-rain-text focus:border-rain-green focus:bg-rain-green/5 focus:outline-none transition-all placeholder-rain-muted/30 font-mono"
            placeholder="> Enter situation report..."></textarea>
        </div>

        <!-- Stakes -->
        <div class="space-y-2 group">
          <label class="text-[10px] uppercase text-rain-muted tracking-wider group-focus-within:text-rain-green transition-colors">Stakes</label>
          <input 
            [ngModel]="inputState().stakes"
            (ngModelChange)="update('stakes', $event)"
            type="text"
            class="w-full bg-rain-panel border border-rain-green/20 p-3 text-sm text-rain-text focus:border-rain-green focus:bg-rain-green/5 focus:outline-none transition-all placeholder-rain-muted/30 font-mono"
            placeholder="> Define risk parameters..." />
        </div>

        <!-- Constraints -->
        <div class="space-y-2 group">
          <label class="text-[10px] uppercase text-rain-muted tracking-wider group-focus-within:text-rain-green transition-colors">Constraints</label>
          <div class="flex flex-wrap gap-2 mb-2">
            @for (c of inputState().constraints; track c; let i = $index) {
              <span class="inline-flex items-center bg-rain-green/10 border border-rain-green/30 px-2 py-1 text-xs text-rain-green">
                {{ c }}
                <button (click)="removeConstraint(i)" class="ml-2 text-rain-green hover:text-white">
                  <mat-icon class="text-[14px] w-[14px] h-[14px] leading-none">close</mat-icon>
                </button>
              </span>
            }
          </div>
          <input 
            #constraintInput
            (keydown.enter)="addConstraint(constraintInput.value); constraintInput.value = ''"
            type="text"
            class="w-full bg-rain-panel border border-rain-green/20 p-3 text-sm text-rain-text focus:border-rain-green focus:bg-rain-green/5 focus:outline-none transition-all placeholder-rain-muted/30 font-mono"
            placeholder="> Add vector (Press Enter)" />
        </div>

        <!-- Non-Negotiables -->
        <div class="space-y-2 group">
          <label class="text-[10px] uppercase text-rain-muted tracking-wider group-focus-within:text-rain-red transition-colors">Non-Negotiables</label>
          <div class="space-y-1 mb-2">
            @for (n of inputState().nonNegotiables; track n; let i = $index) {
              <div class="flex items-center justify-between bg-rain-red/5 border-l-2 border-rain-red px-3 py-2 text-xs text-rain-red">
                <span>{{ n }}</span>
                <button (click)="removeNonNegotiable(i)" class="text-rain-red/70 hover:text-rain-red">
                  <mat-icon class="text-[16px] w-[16px] h-[16px] leading-none">delete</mat-icon>
                </button>
              </div>
            }
          </div>
          <input 
            #nonNegInput
            (keydown.enter)="addNonNegotiable(nonNegInput.value); nonNegInput.value = ''"
            type="text"
            class="w-full bg-rain-panel border border-rain-red/30 p-3 text-sm text-rain-text focus:border-rain-red focus:bg-rain-red/5 focus:outline-none transition-all placeholder-rain-muted/30 font-mono"
            placeholder="> Define red lines (Press Enter)" />
        </div>

        <!-- Horizon -->
        <div class="space-y-2 group">
          <label class="text-[10px] uppercase text-rain-muted tracking-wider group-focus-within:text-rain-green transition-colors">Horizon</label>
          <select 
            [ngModel]="inputState().horizon"
            (ngModelChange)="update('horizon', $event)"
            class="w-full bg-rain-panel border border-rain-green/20 p-3 text-sm text-rain-text focus:border-rain-green focus:bg-rain-green/5 focus:outline-none appearance-none font-mono">
            <option value="Days">Days</option>
            <option value="Weeks">Weeks</option>
            <option value="Quarters">Quarters</option>
          </select>
        </div>

      </div>

      <div class="mt-6 pt-6 border-t border-rain-green/20">
        <button 
          (click)="rainService.runPhase()"
          [disabled]="rainService.isRunning() || rainService.isAlarmActive()"
          [class.border-rain-red]="rainService.isAlarmActive()"
          [class.text-rain-red]="rainService.isAlarmActive()"
          [class.bg-rain-red-10]="rainService.isAlarmActive()"
          class="w-full bg-rain-green/10 border border-rain-green text-rain-green py-4 text-sm font-bold uppercase tracking-[0.2em] hover:bg-rain-green hover:text-black transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 group relative overflow-hidden">
          
          @if (!rainService.isAlarmActive()) {
            <div class="absolute inset-0 bg-rain-green/20 transform -translate-x-full group-hover:translate-x-full transition-transform duration-500"></div>
          }
          
          @if (rainService.isAlarmActive()) {
             <div class="absolute inset-0 bg-rain-red/20 animate-pulse"></div>
             <span class="animate-pulse text-rain-red font-black text-lg">>> DETONATION IN {{ rainService.alarmCountdown() }} <<</span>
          } @else if (rainService.isRunning()) {
            <span class="animate-pulse">>> PROCESSING <<</span>
          } @else {
            <span>INITIATE PHASE</span>
            <mat-icon class="text-sm group-hover:translate-x-1 transition-transform">arrow_forward</mat-icon>
          }
        </button>
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
    .custom-scrollbar::-webkit-scrollbar-thumb:hover {
      background: rgba(255, 255, 255, 0.4);
    }
  `]
})
export class InputPanelComponent {
  rainService = inject(RainService);
  inputState = this.rainService.inputState;
  
  modes: TemplateMode[] = ['Standard', 'Rapid Triage', 'Board Packet'];

  setMode(mode: TemplateMode) {
    this.rainService.updateInput({ template: mode });
  }

  update(field: keyof import('../services/rain.service').InputState, value: any) {
    this.rainService.updateInput({ [field]: value });
  }

  addConstraint(val: string) {
    this.rainService.addConstraint(val);
  }

  removeConstraint(index: number) {
    this.rainService.removeConstraint(index);
  }

  addNonNegotiable(val: string) {
    this.rainService.addNonNegotiable(val);
  }

  removeNonNegotiable(index: number) {
    this.rainService.removeNonNegotiable(index);
  }
}
