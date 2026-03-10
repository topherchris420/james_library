import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RainService } from '../services/rain.service';

@Component({
  selector: 'app-blocking-modal',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (question(); as q) {
      <div class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
        <div class="bg-rain-bg border border-rain-red w-full max-w-lg p-8 shadow-2xl shadow-rain-red/20">
          <div class="text-rain-red text-xs font-bold uppercase tracking-widest mb-4">
            // Blocking Ambiguity Detected
          </div>
          
          <h3 class="text-xl text-white font-mono mb-6 leading-relaxed">
            {{ q }}
          </h3>

          <div class="flex gap-4">
            <input 
              #answerInput
              (keydown.enter)="submit(answerInput.value)"
              type="text" 
              class="flex-1 bg-rain-panel border border-white/20 p-3 text-white focus:border-rain-red focus:outline-none"
              placeholder="Clarify constraint..."
              autofocus />
            
            <button 
              (click)="submit(answerInput.value)"
              class="bg-rain-red text-white px-6 py-3 text-sm font-bold uppercase tracking-wider hover:bg-red-600 transition-colors">
              Resolve
            </button>
          </div>
        </div>
      </div>
    }
  `,
  styles: [`
    .animate-fade-in {
      animation: fadeIn 0.2s ease-out forwards;
    }
    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
  `]
})
export class BlockingModalComponent {
  rainService = inject(RainService);
  question = this.rainService.blockingQuestion;

  submit(answer: string) {
    if (answer.trim()) {
      this.rainService.answerBlockingQuestion(answer);
    }
  }
}
