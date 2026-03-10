import { Component, computed, inject, signal, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { RainService, Scenario, LeverDef } from '../services/rain.service';

@Component({
  selector: 'app-tension-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  encapsulation: ViewEncapsulation.None,
  template: `
    <div class="matter-panel h-full flex flex-col bg-rain-bg relative overflow-hidden font-sans">
      <!-- Header -->
      <div class="p-4 border-b border-white/10 flex items-center justify-between bg-rain-panel/50 backdrop-blur-sm z-10">
        <h2 class="text-xs font-bold uppercase tracking-[0.2em] text-rain-green flex items-center gap-2">
          <mat-icon class="text-sm">view_kanban</mat-icon>
          02 // MATTER
        </h2>
        <div class="mode-toggle flex gap-1 bg-black/20 p-1 rounded-full border border-white/10">
          <button class="mode-btn" [class.active]="mode() === 'use'" (click)="setMode('use')">Use</button>
          <button class="mode-btn" [class.active]="mode() === 'build'" (click)="setMode('build')">Build</button>
          <button class="mode-btn" [class.active]="mode() === 'aac'" (click)="setMode('aac')">AAC</button>
        </div>
      </div>

      <!-- Terminal -->
      <div class="bg-black/40 border-b border-rain-green/10 p-2 font-mono text-[10px] text-rain-green/70 h-32 overflow-y-auto custom-scrollbar relative z-10">
        <div class="absolute inset-0 pointer-events-none bg-gradient-to-b from-transparent to-black/10"></div>
        @for (line of rainService.aiOutput(); track $index) {
          <div class="mb-1 animate-fade-in">{{ line }}</div>
        }
        @if (rainService.isRunning()) {
          <div class="animate-pulse">>> PROCESSING...</div>
        }
      </div>

      <!-- Content Area -->
      <div class="flex-1 overflow-y-auto scrollbar-hide p-4 relative z-0">
        <!-- Grid Background -->
        <div class="absolute inset-0 bg-[linear-gradient(rgba(0,255,65,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(0,255,65,0.02)_1px,transparent_1px)] bg-[size:20px_20px] pointer-events-none"></div>

        @if (mode() === 'use' || mode() === 'aac') {
          <div class="space-y-6 relative z-10" [class.aac-mode]="mode() === 'aac'">
            <!-- Opt-out -->
            <div class="text-center text-[10px] text-rain-muted uppercase tracking-widest opacity-70 mb-4">
              Passing is always okay · Nothing saved without consent
            </div>

            <!-- Questions -->
            @if (currentScenario(); as scenario) {
              <div class="space-y-2">
                @for (lever of scenario.levers; track $index; let idx = $index) {
                <div class="question-card fade-in">
                  <div class="question-header">
                    <div class="question-icon">{{ lever.icon }}</div>
                    <div class="question-prompt flex-1">{{ lever.prompt }}</div>
                    @if (lever.type === 'spectrum') {
                      <div class="text-[10px] font-bold text-rain-spectrum">{{ lever.value }}%</div>
                    }
                  </div>
                  
                  <div class="question-body">
                    <!-- Spectrum -->
                    @if (lever.type === 'spectrum') {
                      <div class="spectrum-lever">
                        <div class="spectrum-track-wrap">
                          <input type="range" class="spectrum-input" min="0" max="100" 
                            [ngModel]="lever.value" (ngModelChange)="updateLeverValue(idx, $event)">
                        </div>
                        <div class="spectrum-labels">
                          <span class="spectrum-label"><span class="emoji">{{ lever.lowEmoji }}</span>{{ lever.lowLabel }}</span>
                          <span class="spectrum-label"><span class="emoji">{{ lever.highEmoji }}</span>{{ lever.highLabel }}</span>
                        </div>
                      </div>
                    }

                    <!-- Variable -->
                    @if (lever.type === 'variable') {
                      <div class="variable-lever">
                        @for (opt of lever.options; track $index; let optIdx = $index) {
                          <button class="variable-option" 
                            [class.selected]="lever.selected === optIdx"
                            (click)="selectVariableOption(idx, optIdx)">
                            <span class="variable-emoji">{{ opt.emoji }}</span>
                            <span class="variable-label">{{ opt.label }}</span>
                          </button>
                        }
                      </div>
                    }

                    <!-- Context -->
                    @if (lever.type === 'context') {
                      <div class="context-lever">
                        <textarea class="context-input" 
                          [placeholder]="lever.placeholder"
                          [rows]="mode() === 'aac' ? 2 : 3"
                          [ngModel]="lever.value"
                          (ngModelChange)="updateLeverValue(idx, $event)"></textarea>
                        <div class="context-options">
                          @for (opt of lever.quickOptions; track opt) {
                            <button class="context-quick-btn" (click)="appendContext(idx, opt)">{{ opt }}</button>
                          }
                        </div>
                      </div>
                    }
                  </div>
                </div>
              }
            </div>

              <!-- Summary -->
              <div class="summary-panel">
                <div class="summary-title">
                  <mat-icon class="text-sm mr-2">summarize</mat-icon>
                  Signal Summary
                </div>
                @for (lever of scenario.levers; track $index) {
                  <div class="summary-row">
                    <span class="summary-label">{{ lever.prompt }}</span>
                    <span class="summary-value text-rain-green">{{ getSummaryValue(lever) }}</span>
                  </div>
                }
              </div>
            } @else {
              <div class="text-center text-rain-muted text-xs py-10 opacity-50">
                >> NO ACTIVE MATTER DETECTED<br>
                >> INITIATE PHASE TO ANALYZE
              </div>
            }

            <!-- Actions -->
            <div class="flex gap-4 mt-6">
              <button class="btn-secondary flex-1" (click)="resetCurrent()">Reset</button>
              <button 
                (click)="rephase()"
                [disabled]="rainService.isRunning() || rainService.isAlarmActive()"
                [class.border-rain-red]="rainService.isAlarmActive()"
                [class.text-rain-red]="rainService.isAlarmActive()"
                [class.bg-rain-red-10]="rainService.isAlarmActive()"
                class="btn-primary flex-1 flex items-center justify-center gap-2 group relative overflow-hidden bg-rain-green/10 border border-rain-green text-rain-green hover:bg-rain-green hover:text-black transition-all">
                
                @if (rainService.isAlarmActive()) {
                   <span class="animate-pulse text-rain-red font-black">>> DETONATION <<</span>
                } @else if (rainService.isRunning()) {
                  <span class="animate-pulse">>> PROCESSING <<</span>
                } @else {
                  <span>REPHASE</span>
                  <mat-icon class="text-sm group-hover:rotate-180 transition-transform duration-500">sync</mat-icon>
                }
              </button>
            </div>
          </div>
        }

        @if (mode() === 'build') {
          <div class="space-y-6 relative z-10 text-white">
            <div class="text-sm font-bold uppercase tracking-widest text-rain-muted">Compose Lever Set</div>
            
            <div class="flex gap-2">
              <button class="builder-type-btn" (click)="addBuilderLever('spectrum')">
                <span class="block text-xl mb-1">◐</span>
                Spectrum
              </button>
              <button class="builder-type-btn" (click)="addBuilderLever('variable')">
                <span class="block text-xl mb-1">◆</span>
                5 Variables
              </button>
              <button class="builder-type-btn" (click)="addBuilderLever('context')">
                <span class="block text-xl mb-1">✎</span>
                Context
              </button>
            </div>

            <div class="space-y-2">
              @for (item of builderLevers(); track $index; let i = $index) {
                <div class="bg-white/5 border border-white/10 p-3 rounded flex items-center gap-3">
                  <span class="text-rain-muted cursor-grab">⠿</span>
                  <div class="flex-1">
                    <div class="text-[10px] font-bold uppercase tracking-wider mb-1" 
                      [class.text-rain-spectrum]="item.type === 'spectrum'"
                      [class.text-rain-variable]="item.type === 'variable'"
                      [class.text-rain-context]="item.type === 'context'">
                      {{ item.type }}
                    </div>
                    <input class="w-full bg-black/30 border border-white/10 rounded px-2 py-1 text-xs text-white" 
                      placeholder="Prompt..." [(ngModel)]="item.prompt">
                  </div>
                  <button class="text-rain-muted hover:text-rain-red" (click)="removeBuilderLever(i)">
                    <mat-icon class="text-sm">close</mat-icon>
                  </button>
                </div>
              }
            </div>

            <button class="btn-primary w-full" (click)="previewBuiltSet()">Preview & Use</button>
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
    :root {
      --rain-spectrum: #5B8FA8;
      --rain-variable: #7A6FA0;
      --rain-context: #8A7A5B;
    }
    .text-rain-spectrum { color: #5B8FA8; }
    .text-rain-variable { color: #7A6FA0; }
    .text-rain-context { color: #8A7A5B; }

    .matter-panel {
      --radius-md: 8px;
      --radius-full: 9999px;
    }

    .mode-btn {
      padding: 4px 12px;
      border-radius: 9999px;
      font-size: 10px;
      text-transform: uppercase;
      font-weight: bold;
      color: rgba(255,255,255,0.5);
      transition: all 0.2s;
    }
    .mode-btn.active {
      background: var(--rain-green);
      color: black;
    }

    .scenario-chip {
      padding: 6px 12px;
      border-radius: 9999px;
      border: 1px solid rgba(255,255,255,0.1);
      background: rgba(255,255,255,0.05);
      color: rgba(255,255,255,0.7);
      font-size: 11px;
      transition: all 0.2s;
    }
    .scenario-chip.active {
      border-color: var(--rain-green);
      background: rgba(0,255,65,0.1);
      color: var(--rain-green);
    }

    .question-card {
      background: rgba(0,0,0,0.2);
      box-shadow: inset 0 1px 3px rgba(0,0,0,0.3);
      border: none;
      border-radius: 6px;
      overflow: hidden;
      margin-bottom: 4px;
    }
    .question-header {
      padding: 6px 10px 2px 10px;
      display: flex;
      gap: 8px;
      align-items: center;
      background: transparent;
    }
    .question-icon {
      width: 18px;
      height: 18px;
      border-radius: 4px;
      background: rgba(255,255,255,0.05);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
    }
    .question-prompt {
      font-size: 11px;
      font-weight: 600;
      color: rgba(255,255,255,0.9);
      margin-top: 0;
    }
    .question-body {
      padding: 2px 10px 6px 10px;
    }

    /* Spectrum */
    .spectrum-input {
      width: 100%;
      height: 4px;
      background: rgba(255,255,255,0.1);
      border-radius: 2px;
      appearance: none;
      outline: none;
    }
    .spectrum-input::-webkit-slider-thumb {
      appearance: none;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: #5B8FA8;
      cursor: pointer;
      border: 2px solid white;
    }
    .spectrum-value {
      display: none; /* Moved to header */
    }
    .spectrum-labels {
      display: flex;
      justify-content: space-between;
      margin-top: 2px;
      font-size: 9px;
      color: rgba(255,255,255,0.5);
    }

    /* Variable */
    .variable-lever {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }
    .variable-option {
      flex: 1;
      min-width: 40px;
      padding: 4px 2px;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 4px;
      background: transparent;
      text-align: center;
      transition: all 0.2s;
    }
    .variable-option.selected {
      border-color: #7A6FA0;
      background: rgba(122,111,160,0.2);
    }
    .variable-emoji { display: block; font-size: 14px; margin-bottom: 0px; }
    .variable-label { font-size: 8px; color: rgba(255,255,255,0.8); }

    /* Context */
    .context-input {
      width: 100%;
      background: rgba(0,0,0,0.3);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 6px;
      padding: 8px;
      color: white;
      font-size: 12px;
      resize: none;
    }
    .context-input:focus { outline: none; border-color: #8A7A5B; }
    .context-options { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
    .context-quick-btn {
      padding: 4px 10px;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 9999px;
      font-size: 10px;
      color: rgba(255,255,255,0.6);
      transition: all 0.2s;
    }
    .context-quick-btn:hover { border-color: #8A7A5B; color: #8A7A5B; }

    /* Summary */
    .summary-panel {
      background: rgba(0,0,0,0.2);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 12px;
      padding: 16px;
    }
    .summary-title {
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
      color: rgba(255,255,255,0.5);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
    }
    .summary-row {
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      font-size: 11px;
    }
    .summary-label { color: rgba(255,255,255,0.6); }
    .summary-value { font-weight: bold; }

    /* Buttons */
    .btn-primary {
      background: var(--rain-green);
      color: black;
      font-weight: bold;
      text-transform: uppercase;
      padding: 10px;
      border-radius: 6px;
      font-size: 11px;
      letter-spacing: 0.05em;
    }
    .btn-secondary {
      background: transparent;
      border: 1px solid rgba(255,255,255,0.2);
      color: white;
      font-weight: bold;
      text-transform: uppercase;
      padding: 10px;
      border-radius: 6px;
      font-size: 11px;
      letter-spacing: 0.05em;
    }

    /* Builder */
    .builder-type-btn {
      flex: 1;
      padding: 12px;
      border: 1px dashed rgba(255,255,255,0.2);
      border-radius: 8px;
      color: rgba(255,255,255,0.6);
      font-size: 10px;
      text-transform: uppercase;
      transition: all 0.2s;
    }
    .builder-type-btn:hover {
      border-color: var(--rain-green);
      color: var(--rain-green);
      background: rgba(0,255,65,0.05);
    }

    /* AAC Mode Overrides */
    .aac-mode .variable-option { min-width: 80px; padding: 12px; }
    .aac-mode .variable-emoji { font-size: 28px; }
    .aac-mode .question-prompt { font-size: 16px; }
    .aac-mode .spectrum-input::-webkit-slider-thumb { width: 24px; height: 24px; }
  `]
})
export class TensionPanelComponent {
  rainService = inject(RainService);
  mode = signal<'use' | 'build' | 'aac'>('use');
  builderLevers = signal<any[]>([]);

  // Use activeScenario from RainService instead of local scenarios
  currentScenario = this.rainService.activeScenario;

  setMode(m: 'use' | 'build' | 'aac') {
    this.mode.set(m);
  }

  updateLeverValue(idx: number, val: any) {
    const scenario = this.currentScenario();
    if (scenario) {
      scenario.levers[idx].value = val;
    }
  }

  selectVariableOption(leverIdx: number, optIdx: number) {
    const scenario = this.currentScenario();
    if (scenario) {
      scenario.levers[leverIdx].selected = optIdx;
    }
  }

  appendContext(idx: number, text: string) {
    const scenario = this.currentScenario();
    if (scenario) {
      const current = scenario.levers[idx].value || '';
      scenario.levers[idx].value = current ? current + ', ' + text : text;
    }
  }

  getSummaryValue(lever: LeverDef): string {
    if (lever.type === 'spectrum') return lever.value + '%';
    if (lever.type === 'variable') {
      if (lever.selected === null || lever.selected === undefined) return '—';
      const opt = lever.options![lever.selected];
      return `${opt.emoji} ${opt.label}`;
    }
    return lever.value || '—';
  }

  resetCurrent() {
    const scenario = this.currentScenario();
    if (scenario) {
      scenario.levers.forEach(l => {
        if (l.type === 'spectrum') l.value = 50;
        if (l.type === 'variable') l.selected = null;
        if (l.type === 'context') l.value = '';
      });
    }
  }

  submitSignal() {
    alert('Signal Received. The braid holds.');
    this.resetCurrent();
  }

  rephase() {
    this.rainService.addLog('REPHASE INITIATED FROM MATTER PANEL');
    this.rainService.runPhase();
  }

  // Builder Logic
  addBuilderLever(type: 'spectrum' | 'variable' | 'context') {
    this.builderLevers.update(l => [...l, { type, prompt: '' }]);
  }

  removeBuilderLever(idx: number) {
    this.builderLevers.update(l => l.filter((_, i) => i !== idx));
  }

  previewBuiltSet() {
    if (this.builderLevers().length < 1) return;
    
    const newScenario: Scenario = {
      id: 'custom-' + Date.now(),
      label: '🛠️ Custom Set',
      levers: this.builderLevers().map(bl => {
        if (bl.type === 'spectrum') {
          return {
            type: 'spectrum',
            prompt: bl.prompt || 'Rate this',
            icon: '◐', iconBg: 'rgba(91,143,168,0.2)',
            lowLabel: 'Low', lowEmoji: '⬇️',
            highLabel: 'High', highEmoji: '⬆️',
            value: 50
          };
        } else if (bl.type === 'variable') {
          return {
            type: 'variable',
            prompt: bl.prompt || 'Choose one',
            icon: '◆', iconBg: 'rgba(122,111,160,0.2)',
            options: [
              { emoji: '1️⃣', label: 'Option 1' },
              { emoji: '2️⃣', label: 'Option 2' },
              { emoji: '3️⃣', label: 'Option 3' },
              { emoji: '4️⃣', label: 'Option 4' },
              { emoji: '5️⃣', label: 'Option 5' }
            ],
            selected: null,
            value: null
          };
        } else {
          return {
            type: 'context',
            prompt: bl.prompt || 'Tell us more',
            icon: '✎', iconBg: 'rgba(138,122,91,0.2)',
            placeholder: 'Type response...',
            quickOptions: ['Yes', 'No', 'Maybe'],
            value: ''
          };
        }
      })
    };

    this.rainService.activeScenario.set(newScenario);
    this.setMode('use');
  }
}
