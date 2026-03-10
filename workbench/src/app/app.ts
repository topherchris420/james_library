import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TopNavComponent } from './components/top-nav.component';
import { InputPanelComponent } from './components/input-panel.component';
import { TensionPanelComponent } from './components/tension-panel.component';
import { LeverPanelComponent } from './components/lever-panel.component';
import { ArtifactBarComponent } from './components/artifact-bar.component';
import { BlockingModalComponent } from './components/blocking-modal.component';
import { MetricsLibraryComponent } from './components/metrics-library.component';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-root',
  imports: [
    TopNavComponent,
    InputPanelComponent,
    TensionPanelComponent,
    LeverPanelComponent,
    ArtifactBarComponent,
    BlockingModalComponent,
    MetricsLibraryComponent
  ],
  template: `
    <div class="h-screen w-screen flex flex-col overflow-hidden bg-rain-bg text-rain-text font-mono relative" 
         (mousemove)="onDrag($event)" 
         (mouseup)="stopDrag()"
         (mouseleave)="stopDrag()">
      
      <!-- Overlays -->
      <app-blocking-modal />
      <app-metrics-library />

      <!-- Top Nav -->
      <app-top-nav />

      <!-- Main Workspace -->
      <div class="flex-1 flex overflow-hidden pl-0 relative">
        <!-- Left Panel: Input -->
        <div [style.width.%]="leftWidth" class="h-full relative flex-shrink-0">
          <app-input-panel />
          <!-- Resizer 1 (Controller) -->
          <div class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-rain-green/50 z-50 transition-colors flex items-center justify-center group"
               (mousedown)="startDrag($event, 'left')">
             <div class="h-8 w-[1px] bg-rain-green/30 group-hover:bg-rain-green"></div>
          </div>
        </div>

        <!-- Center Panel: Matter -->
        <div [style.width.%]="centerWidth" class="h-full relative flex-shrink-0">
          <app-tension-panel />
          <!-- Resizer 2 (Controller) -->
          <div class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-rain-green/50 z-50 transition-colors flex items-center justify-center group"
               (mousedown)="startDrag($event, 'center')">
             <div class="h-8 w-[1px] bg-rain-green/30 group-hover:bg-rain-green"></div>
          </div>
        </div>

        <!-- Right Panel: System -->
        <div [style.width.%]="rightWidth" class="h-full flex-shrink-0">
          <app-lever-panel />
        </div>
      </div>

      <!-- Bottom Bar: Artifact -->
      <app-artifact-bar />
    </div>
  `,
  styles: []
})
export class App {
  leftWidth = 35;
  centerWidth = 40;
  rightWidth = 25;

  private isDragging = false;
  private dragTarget: 'left' | 'center' | null = null;

  startDrag(event: MouseEvent, target: 'left' | 'center') {
    this.isDragging = true;
    this.dragTarget = target;
    event.preventDefault();
  }

  onDrag(event: MouseEvent) {
    if (!this.isDragging) return;

    const containerWidth = window.innerWidth;
    const xPercent = (event.clientX / containerWidth) * 100;
    const minWidth = 15;

    if (this.dragTarget === 'left') {
      let newLeft = xPercent;
      if (newLeft < minWidth) newLeft = minWidth;
      if (100 - newLeft - this.rightWidth < minWidth) {
        newLeft = 100 - this.rightWidth - minWidth;
      }
      this.leftWidth = newLeft;
      this.centerWidth = 100 - this.leftWidth - this.rightWidth;

    } else if (this.dragTarget === 'center') {
      let newCenterRight = xPercent;
      if (newCenterRight - this.leftWidth < minWidth) {
        newCenterRight = this.leftWidth + minWidth;
      }
      if (100 - newCenterRight < minWidth) {
        newCenterRight = 100 - minWidth;
      }
      this.centerWidth = newCenterRight - this.leftWidth;
      this.rightWidth = 100 - this.leftWidth - this.centerWidth;
    }
  }

  stopDrag() {
    this.isDragging = false;
    this.dragTarget = null;
  }
}
