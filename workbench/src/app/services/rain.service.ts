import { Injectable, signal, computed } from '@angular/core';

export type TemplateMode = 'Standard' | 'Rapid Triage' | 'Board Packet';
export type Horizon = 'Days' | 'Weeks' | 'Quarters';
export type Severity = 'red' | 'amber' | 'green';

export interface InputState {
  context: string;
  stakes: string;
  constraints: string[];
  nonNegotiables: string[];
  horizon: Horizon;
  template: TemplateMode;
}

export interface Tension {
  id: string;
  title: string;
  axis: 'Goal vs Incentive' | 'Urgency vs Capacity' | 'Risk Claimed vs Owned' | 'Control Desired vs Available';
  severity: Severity;
  sourceField: string;
  description: string;
  expanded: boolean;
  recycled?: boolean;
}

export interface Lever {
  id: string;
  owner: string;
  description: string;
  metric: string;
  horizonStart: string;
  horizonEnd: string;
  type: 'demand_binary' | 'demand_multi';
  options?: string[];
  response?: string;
  associatedTensionId?: string;
}

export interface Artifact {
  type: 'quote' | 'riddle' | 'checklist';
  content: string;
}

export interface LeverOption {
  emoji: string;
  label: string;
}

export interface LeverDef {
  type: 'spectrum' | 'variable' | 'context';
  prompt: string;
  icon: string;
  iconBg: string;
  // Spectrum
  lowLabel?: string;
  lowEmoji?: string;
  highLabel?: string;
  highEmoji?: string;
  value: any;
  // Variable
  options?: LeverOption[];
  selected?: number | null;
  // Context
  placeholder?: string;
  quickOptions?: string[];
}

export interface Scenario {
  id: string;
  label: string;
  levers: LeverDef[];
}

@Injectable({
  providedIn: 'root'
})
export class RainService {
  // State
  readonly inputState = signal<InputState>({
    context: '',
    stakes: '',
    constraints: [],
    nonNegotiables: [],
    horizon: 'Weeks',
    template: 'Standard'
  });

  readonly tensions = signal<Tension[]>([]);
  readonly levers = signal<Lever[]>([]); // Legacy
  readonly activeScenario = signal<Scenario | null>(null); // New Matter System
  readonly artifact = signal<Artifact | null>(null);
  readonly isRunning = signal(false);
  readonly isAlarmActive = signal(false);
  readonly alarmCountdown = signal(0);
  readonly blockingQuestion = signal<string | null>(null);
  readonly showMetricsLibrary = signal<{ leverId: string } | null>(null);
  readonly showHistory = signal(false);
  readonly sessions = signal<{ id: string; date: Date; input: InputState }[]>([]);
  readonly logs = signal<{ timestamp: Date; message: string }[]>([]);
  readonly logDestructTime = signal<Date>(new Date(Date.now() + 30 * 60000));
  readonly aiOutput = signal<string[]>(['>> SYSTEM READY', '>> AWAITING INPUT...']);

  // Actions
  addLog(message: string) {
    this.logs.update(l => [{ timestamp: new Date(), message }, ...l]);
  }

  updateInput(partial: Partial<InputState>) {
    this.inputState.update(s => ({ ...s, ...partial }));
  }

  toggleHistory() {
    this.showHistory.update(v => !v);
  }

  openMetricsLibrary(leverId: string) {
    this.showMetricsLibrary.set({ leverId });
  }

  closeMetricsLibrary() {
    this.showMetricsLibrary.set(null);
  }

  selectMetric(metric: string) {
    const state = this.showMetricsLibrary();
    if (state) {
      this.updateLever(state.leverId, { metric });
      this.closeMetricsLibrary();
    }
  }

  answerBlockingQuestion(answer: string) {
    this.blockingQuestion.set(null);
    this.addConstraint(answer);
    this.runPhase(); // Re-run
  }

  rotateArtifact() {
    const artifacts: Artifact[] = [
      { type: 'quote', content: 'The only way out is through.' },
      { type: 'riddle', content: 'I grow when I eat, but die when I drink. What am I?' },
      { type: 'checklist', content: 'Verify audit trail. Confirm owner consent. Check budget cap.' },
      { type: 'quote', content: 'Chaos is a ladder.' }
    ];
    const current = this.artifact();
    let next = artifacts[Math.floor(Math.random() * artifacts.length)];
    while (next.content === current?.content) {
      next = artifacts[Math.floor(Math.random() * artifacts.length)];
    }
    this.artifact.set(next);
  }

  addConstraint(val: string) {
    if (!val) return;
    this.inputState.update(s => ({ ...s, constraints: [...s.constraints, val] }));
  }

  removeConstraint(index: number) {
    this.inputState.update(s => ({
      ...s,
      constraints: s.constraints.filter((_, i) => i !== index)
    }));
  }

  addNonNegotiable(val: string) {
    if (!val) return;
    this.inputState.update(s => ({ ...s, nonNegotiables: [...s.nonNegotiables, val] }));
  }

  removeNonNegotiable(index: number) {
    this.inputState.update(s => ({
      ...s,
      nonNegotiables: s.nonNegotiables.filter((_, i) => i !== index)
    }));
  }

  toggleTensionExpand(id: string) {
    this.tensions.update(ts => ts.map(t => t.id === id ? { ...t, expanded: !t.expanded } : t));
  }

  recycleTension(id: string) {
    this.tensions.update(ts => ts.map(t => t.id === id ? { ...t, recycled: true, severity: 'amber' } : t));
    this.addLog(`TENSION RECYCLED: ${id}`);
  }

  updateLever(id: string, partial: Partial<Lever>) {
    this.levers.update(ls => ls.map(l => l.id === id ? { ...l, ...partial } : l));
  }

  async runPhase() {
    // Start Alarm Sequence
    this.isAlarmActive.set(true);
    
    for (let i = 5; i >= 0; i--) {
      this.alarmCountdown.set(i);
      await new Promise(resolve => setTimeout(resolve, 1000));
    }

    this.isAlarmActive.set(false);
    this.isRunning.set(true);
    this.addLog('PHASE INITIATED: SEQUENCE STARTED');
    this.aiOutput.set(['>> PHASE INITIATED', '>> ANALYZING INPUT VECTORS...', '>> CALCULATING PROBABILITIES...']);
    
    // Simulate engine delay
    await new Promise(resolve => setTimeout(resolve, 1200));

    this.aiOutput.update(o => [...o, '>> TENSION DETECTED', '>> GENERATING LEVERS']);

    // 20% chance of blocking question
    if (Math.random() < 0.2 && !this.blockingQuestion()) {
      this.blockingQuestion.set("Is the 'Launch by Friday' constraint driven by external contract or internal goal?");
      this.isRunning.set(false);
      return;
    }

    // Generate Dynamic Scenario based on Input
    const subject = this.inputState().context || 'Current Situation';
    const newScenario: Scenario = {
      id: 'generated-' + Date.now(),
      label: '⚡ AI Generated',
      levers: [
        {
          type: 'spectrum',
          prompt: `How critical is "${subject.substring(0, 20)}..."?`,
          icon: '📊',
          iconBg: 'rgba(91,143,168,0.2)',
          lowLabel: 'Low', lowEmoji: '☁️',
          highLabel: 'Critical', highEmoji: '🔥',
          value: 50
        },
        {
          type: 'variable',
          prompt: 'Recommended Action Path:',
          icon: '💠',
          iconBg: 'rgba(122,111,160,0.2)',
          options: [
            { emoji: '🛡️', label: 'Defend' },
            { emoji: '⚔️', label: 'Attack' },
            { emoji: '🤝', label: 'Negotiate' },
            { emoji: '🛑', label: 'Abort' }
          ],
          selected: null,
          value: null
        }
      ]
    };
    
    this.activeScenario.set(newScenario);
    this.aiOutput.update(o => [...o, '>> LEVERS SURFACED', '>> AWAITING HUMAN INPUT']);

    // Mock Output
    const mockTensions: Tension[] = [
      {
        id: '1',
        title: 'Velocity vs. Verification',
        axis: 'Urgency vs Capacity',
        severity: 'red',
        sourceField: 'Constraints: "Launch by Friday"',
        description: 'The demand for immediate release conflicts with the requirement for 100% audit coverage.',
        expanded: false
      },
      {
        id: '2',
        title: 'Shadow Ownership',
        axis: 'Risk Claimed vs Owned',
        severity: 'amber',
        sourceField: 'Context: "Marketing owns the message"',
        description: 'Marketing claims message ownership but Engineering holds the risk of compliance failure.',
        expanded: false
      },
      {
        id: '3',
        title: 'Budget Illusion',
        axis: 'Goal vs Incentive',
        severity: 'green',
        sourceField: 'Stakes: "Must reduce burn"',
        description: 'Goal is burn reduction, but incentives reward headcount growth.',
        expanded: false
      }
    ];

    const mockLevers: Lever[] = [
      {
        id: '1',
        owner: 'Engineering Lead',
        description: 'Authorize immediate decoupling of audit from release path?',
        metric: 'Time-to-decision',
        horizonStart: new Date().toISOString().split('T')[0],
        horizonEnd: new Date(Date.now() + 86400000 * 7).toISOString().split('T')[0],
        type: 'demand_binary',
        associatedTensionId: '1'
      },
      {
        id: '2',
        owner: 'Product Owner',
        description: 'Select compliance strategy:',
        metric: 'Audit pass rate',
        horizonStart: new Date().toISOString().split('T')[0],
        horizonEnd: new Date(Date.now() + 86400000 * 3).toISOString().split('T')[0],
        type: 'demand_multi',
        options: ['Full Audit', 'Risk-Based Sampling', 'Waiver'],
        associatedTensionId: '2'
      }
    ];

    this.tensions.set(mockTensions);
    this.levers.set(mockLevers);
    this.artifact.set({ type: 'quote', content: 'The only way out is through.' });
    
    // Save history
    this.sessions.update(s => [
      { id: Math.random().toString(36).substring(7), date: new Date(), input: { ...this.inputState() } },
      ...s
    ]);

    this.isRunning.set(false);
  }
}
