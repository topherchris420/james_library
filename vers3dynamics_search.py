#!/usr/bin/env python3
"""
Vers3Dynamics Search - RF Spectrum Situational Awareness System

A real-time 3D visualization platform for monitoring electromagnetic spectrum activity,
detecting patterns, anomalies, and temporal stability in the RF environment.

Author: Vers3Dynamics
License: MIT
"""

import numpy as np
import plotly.graph_objects as go
from flask import Flask, render_template_string, jsonify
from flask_cors import CORS
from threading import Thread, Lock
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Tuple, Dict
import json
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """System configuration parameters"""
    # Frequency spectrum
    FREQ_START = 88e6      # 88 MHz
    FREQ_END = 2.4e9       # 2.4 GHz
    NUM_BANDS = 64         # Number of frequency bands to monitor
    
    # Temporal parameters
    SAMPLE_RATE = 10       # Samples per second
    WINDOW_SIZE = 100      # Historical samples for baseline calculation
    UPDATE_INTERVAL = 0.1  # Seconds between updates
    
    # Anomaly detection
    ANOMALY_THRESHOLD = 2.5    # Standard deviations for anomaly detection
    STABILITY_THRESHOLD = 0.15  # Variance threshold for stability assessment
    
    # Visualization
    PORT = 5000
    AUTO_ROTATE = True
    POINT_SIZE = 8
    
    # Simulation (when no real SDR available)
    SIMULATE_SDR = True
    NUM_SIGNAL_SOURCES = 8


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class SpectralNode:
    """Represents a frequency band in the spectral field"""
    frequency: float        # Center frequency (Hz)
    power: float           # Current power level (dBm)
    baseline: float        # Historical baseline power
    variance: float        # Temporal variance
    anomaly_score: float   # Deviation from baseline
    stability: float       # Temporal stability metric (0-1)
    band_class: str       # "low", "mid", "high" frequency classification
    position: Tuple[float, float, float]  # 3D coordinates
    history: deque         # Recent power measurements


@dataclass
class SignalSource:
    """Simulated RF signal source"""
    frequency: float       # Center frequency
    bandwidth: float       # Signal bandwidth
    power: float          # Base power level
    modulation: str       # Type of modulation
    duty_cycle: float     # Transmission duty cycle
    phase: float         # Current phase


# =============================================================================
# RF SIGNAL PROCESSING
# =============================================================================

class RFProcessor:
    """Processes RF spectrum data and computes spectral features"""
    
    def __init__(self, config: Config):
        self.config = config
        self.bands = self._initialize_bands()
        self.lock = Lock()
        
    def _initialize_bands(self) -> List[SpectralNode]:
        """Initialize frequency band nodes"""
        bands = []
        freq_range = self.config.FREQ_END - self.config.FREQ_START
        freq_step = freq_range / self.config.NUM_BANDS
        
        for i in range(self.config.NUM_BANDS):
            freq = self.config.FREQ_START + (i + 0.5) * freq_step
            
            # Classify band
            normalized_freq = i / self.config.NUM_BANDS
            if normalized_freq < 0.33:
                band_class = "low"
            elif normalized_freq < 0.67:
                band_class = "mid"
            else:
                band_class = "high"
            
            # Calculate 3D position (cylindrical arrangement)
            angle = 2 * np.pi * i / self.config.NUM_BANDS
            radius = 10 + 5 * normalized_freq
            height = normalized_freq * 20 - 10
            
            position = (
                radius * np.cos(angle),
                radius * np.sin(angle),
                height
            )
            
            node = SpectralNode(
                frequency=freq,
                power=-90.0,  # Initial noise floor
                baseline=-90.0,
                variance=0.0,
                anomaly_score=0.0,
                stability=1.0,
                band_class=band_class,
                position=position,
                history=deque(maxlen=self.config.WINDOW_SIZE)
            )
            bands.append(node)
        
        return bands
    
    def update_spectrum(self, power_data: np.ndarray):
        """Update spectral nodes with new power measurements"""
        with self.lock:
            for i, node in enumerate(self.bands):
                if i < len(power_data):
                    power = power_data[i]
                    node.history.append(power)
                    node.power = power
                    
                    # Compute statistics
                    if len(node.history) >= 10:
                        history_array = np.array(node.history)
                        node.baseline = np.median(history_array)
                        node.variance = np.var(history_array)
                        
                        # Anomaly score (z-score)
                        std = np.sqrt(node.variance) if node.variance > 0 else 1.0
                        node.anomaly_score = abs(power - node.baseline) / std
                        
                        # Stability metric (inverse of normalized variance)
                        normalized_var = node.variance / (abs(node.baseline) + 1e-6)
                        node.stability = max(0, 1 - normalized_var / self.config.STABILITY_THRESHOLD)
    
    def get_spectral_state(self) -> Dict:
        """Get current spectral state for visualization"""
        with self.lock:
            nodes_data = []
            for node in self.bands:
                nodes_data.append({
                    'frequency': node.frequency,
                    'power': node.power,
                    'baseline': node.baseline,
                    'anomaly_score': node.anomaly_score,
                    'stability': node.stability,
                    'band_class': node.band_class,
                    'position': node.position
                })
            
            return {
                'nodes': nodes_data,
                'timestamp': datetime.now().isoformat(),
                'num_anomalies': sum(1 for n in self.bands if n.anomaly_score > self.config.ANOMALY_THRESHOLD)
            }


# =============================================================================
# SDR INTERFACE / SIMULATOR
# =============================================================================

class SpectrumSource:
    """Provides RF spectrum data - simulated or from real SDR"""
    
    def __init__(self, config: Config):
        self.config = config
        self.sources = self._initialize_sources()
        self.time = 0
        
    def _initialize_sources(self) -> List[SignalSource]:
        """Initialize simulated signal sources"""
        sources = []
        freq_range = self.config.FREQ_END - self.config.FREQ_START
        
        for i in range(self.config.NUM_SIGNAL_SOURCES):
            freq = self.config.FREQ_START + np.random.random() * freq_range
            sources.append(SignalSource(
                frequency=freq,
                bandwidth=1e6 * (0.5 + np.random.random() * 2),  # 0.5-2.5 MHz
                power=-60 + np.random.random() * 30,  # -60 to -30 dBm
                modulation=np.random.choice(['FM', 'AM', 'QAM', 'PSK']),
                duty_cycle=0.3 + np.random.random() * 0.7,
                phase=np.random.random() * 2 * np.pi
            ))
        
        return sources
    
    def get_spectrum_snapshot(self) -> np.ndarray:
        """Get current spectrum power across all bands"""
        freq_range = self.config.FREQ_END - self.config.FREQ_START
        freq_step = freq_range / self.config.NUM_BANDS
        
        # Initialize with noise floor
        spectrum = np.random.normal(-90, 2, self.config.NUM_BANDS)
        
        # Add signal sources
        for source in self.sources:
            # Determine which bands are affected
            source_band = int((source.frequency - self.config.FREQ_START) / freq_step)
            bandwidth_bands = int(source.bandwidth / freq_step) + 1
            
            for offset in range(-bandwidth_bands, bandwidth_bands + 1):
                band_idx = source_band + offset
                if 0 <= band_idx < self.config.NUM_BANDS:
                    # Signal envelope
                    distance = abs(offset) / bandwidth_bands
                    envelope = np.exp(-distance * 3)
                    
                    # Temporal modulation
                    active = np.sin(source.phase + self.time) * 0.5 + 0.5 > (1 - source.duty_cycle)
                    
                    if active:
                        signal_power = source.power * envelope + np.random.normal(0, 1)
                        spectrum[band_idx] = 10 * np.log10(
                            10**(spectrum[band_idx]/10) + 10**(signal_power/10)
                        )
            
            # Update source phase
            source.phase += 0.1 + np.random.random() * 0.2
        
        # Add occasional anomalies
        if np.random.random() < 0.05:
            anomaly_band = np.random.randint(0, self.config.NUM_BANDS)
            spectrum[anomaly_band] += 20 + np.random.random() * 15
        
        self.time += 0.1
        return spectrum


# =============================================================================
# VISUALIZATION ENGINE
# =============================================================================

class Visualizer:
    """Generates 3D visualization of spectral field"""
    
    def __init__(self, config: Config):
        self.config = config
        
    def create_3d_scene(self, spectral_state: Dict) -> str:
        """Create Plotly 3D visualization"""
        nodes = spectral_state['nodes']
        
        # Extract data for visualization
        x = [n['position'][0] for n in nodes]
        y = [n['position'][1] for n in nodes]
        z = [n['position'][2] for n in nodes]
        
        # Size based on power (normalized)
        powers = np.array([n['power'] for n in nodes])
        power_normalized = (powers - powers.min()) / (powers.max() - powers.min() + 1e-6)
        sizes = 5 + power_normalized * 20
        
        # Color based on anomaly score and band class
        colors = []
        for node in nodes:
            if node['anomaly_score'] > self.config.ANOMALY_THRESHOLD:
                colors.append('red')  # Anomaly
            elif node['band_class'] == 'low':
                colors.append('cyan')
            elif node['band_class'] == 'mid':
                colors.append('lime')
            else:
                colors.append('magenta')
        
        # Opacity based on stability
        opacities = [n['stability'] * 0.8 + 0.2 for n in nodes]
        
        # Create hover text
        hover_texts = []
        for node in nodes:
            freq_mhz = node['frequency'] / 1e6
            text = (f"Freq: {freq_mhz:.1f} MHz<br>"
                   f"Power: {node['power']:.1f} dBm<br>"
                   f"Baseline: {node['baseline']:.1f} dBm<br>"
                   f"Anomaly: {node['anomaly_score']:.2f}σ<br>"
                   f"Stability: {node['stability']:.2%}<br>"
                   f"Class: {node['band_class']}")
            hover_texts.append(text)
        
        # Create spectral nodes trace
        nodes_trace = go.Scatter3d(
            x=x, y=y, z=z,
            mode='markers',
            marker=dict(
                size=sizes,
                color=colors,
                opacity=opacities,
                line=dict(color='white', width=0.5)
            ),
            text=hover_texts,
            hoverinfo='text',
            name='Spectral Nodes'
        )
        
        # Observer origin
        observer_trace = go.Scatter3d(
            x=[0], y=[0], z=[0],
            mode='markers',
            marker=dict(
                size=15,
                color='yellow',
                symbol='diamond',
                line=dict(color='orange', width=2)
            ),
            text=['Observer Platform'],
            hoverinfo='text',
            name='Observer'
        )
        
        # Create figure
        fig = go.Figure(data=[nodes_trace, observer_trace])
        
        # Layout
        fig.update_layout(
            title=dict(
                text=f"Vers3Dynamics Search - Spectral Situational Awareness<br>"
                     f"<sub>Timestamp: {spectral_state['timestamp']} | "
                     f"Anomalies: {spectral_state['num_anomalies']}</sub>",
                x=0.5,
                xanchor='center'
            ),
            scene=dict(
                xaxis=dict(title='X (Spatial)', backgroundcolor='rgb(10, 10, 30)', 
                          gridcolor='rgb(30, 30, 60)', showbackground=True),
                yaxis=dict(title='Y (Spatial)', backgroundcolor='rgb(10, 10, 30)', 
                          gridcolor='rgb(30, 30, 60)', showbackground=True),
                zaxis=dict(title='Z (Frequency)', backgroundcolor='rgb(10, 10, 30)', 
                          gridcolor='rgb(30, 30, 60)', showbackground=True),
                bgcolor='rgb(5, 5, 20)',
                camera=dict(
                    eye=dict(x=1.5, y=1.5, z=1.2)
                )
            ),
            paper_bgcolor='rgb(0, 0, 15)',
            font=dict(color='rgb(200, 200, 255)', family='Courier New'),
            showlegend=True,
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(0, 0, 0, 0.7)',
                bordercolor='cyan',
                borderwidth=1
            ),
            margin=dict(l=0, r=0, t=80, b=0)
        )
        
        return fig.to_json()


# =============================================================================
# CORE SYSTEM
# =============================================================================

class Vers3DynamicsSearch:
    """Main system coordinator"""
    
    def __init__(self):
        self.config = Config()
        self.processor = RFProcessor(self.config)
        self.source = SpectrumSource(self.config)
        self.visualizer = Visualizer(self.config)
        self.running = False
        self.acquisition_thread = None
        
        logger.info("Vers3Dynamics Search initialized")
        logger.info(f"Monitoring: {self.config.FREQ_START/1e6:.1f} - {self.config.FREQ_END/1e9:.3f} GHz")
        logger.info(f"Bands: {self.config.NUM_BANDS} | Update rate: {self.config.SAMPLE_RATE} Hz")
    
    def start_acquisition(self):
        """Start RF spectrum acquisition"""
        self.running = True
        self.acquisition_thread = Thread(target=self._acquisition_loop, daemon=True)
        self.acquisition_thread.start()
        logger.info("Spectrum acquisition started")
    
    def stop_acquisition(self):
        """Stop RF spectrum acquisition"""
        self.running = False
        if self.acquisition_thread:
            self.acquisition_thread.join(timeout=2)
        logger.info("Spectrum acquisition stopped")
    
    def _acquisition_loop(self):
        """Continuous acquisition and processing loop"""
        while self.running:
            try:
                # Get spectrum snapshot
                spectrum = self.source.get_spectrum_snapshot()
                
                # Process spectrum
                self.processor.update_spectrum(spectrum)
                
                # Sleep until next sample
                time.sleep(1.0 / self.config.SAMPLE_RATE)
                
            except Exception as e:
                logger.error(f"Acquisition error: {e}")
                time.sleep(0.5)
    
    def get_visualization_data(self) -> str:
        """Get current visualization data as JSON"""
        spectral_state = self.processor.get_spectral_state()
        return self.visualizer.create_3d_scene(spectral_state)


# =============================================================================
# WEB INTERFACE
# =============================================================================

# HTML template for the web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vers3Dynamics Search - RF Spectrum Monitor</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #0a0a1e 0%, #1a0a2e 100%);
            color: #00ffff;
            overflow: hidden;
        }
        
        .header {
            background: rgba(0, 0, 0, 0.8);
            padding: 15px 30px;
            border-bottom: 2px solid #00ffff;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 24px;
            text-shadow: 0 0 10px #00ffff;
        }
        
        .status {
            display: flex;
            gap: 20px;
            align-items: center;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #00ff00;
            box-shadow: 0 0 10px #00ff00;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .container {
            height: calc(100vh - 80px);
            padding: 20px;
        }
        
        #plot {
            width: 100%;
            height: 100%;
            border: 2px solid #00ffff;
            border-radius: 8px;
            background: rgba(0, 0, 0, 0.5);
        }
        
        .legend-panel {
            position: absolute;
            bottom: 30px;
            right: 30px;
            background: rgba(0, 0, 0, 0.85);
            border: 1px solid #00ffff;
            border-radius: 8px;
            padding: 15px;
            min-width: 250px;
        }
        
        .legend-panel h3 {
            margin-bottom: 10px;
            font-size: 14px;
            border-bottom: 1px solid #00ffff;
            padding-bottom: 5px;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 8px 0;
            font-size: 12px;
        }
        
        .color-box {
            width: 20px;
            height: 20px;
            border: 1px solid #fff;
        }
        
        .loading {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 24px;
            text-align: center;
        }
        
        .spinner {
            border: 4px solid rgba(0, 255, 255, 0.1);
            border-top: 4px solid #00ffff;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚡ Vers3Dynamics Search</h1>
        <div class="status">
            <div class="status-item">
                <div class="indicator"></div>
                <span>ACTIVE</span>
            </div>
            <div class="status-item">
                <span id="update-counter">Updates: 0</span>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div id="plot"></div>
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <div>Initializing Spectral Analysis...</div>
        </div>
    </div>
    
    <div class="legend-panel">
        <h3>LEGEND</h3>
        <div class="legend-item">
            <div class="color-box" style="background: cyan;"></div>
            <span>Low Frequency (VHF/UHF)</span>
        </div>
        <div class="legend-item">
            <div class="color-box" style="background: lime;"></div>
            <span>Mid Frequency (L/S Band)</span>
        </div>
        <div class="legend-item">
            <div class="color-box" style="background: magenta;"></div>
            <span>High Frequency (C/X Band)</span>
        </div>
        <div class="legend-item">
            <div class="color-box" style="background: red;"></div>
            <span>⚠ ANOMALY DETECTED</span>
        </div>
        <div class="legend-item">
            <div class="color-box" style="background: yellow;"></div>
            <span>◆ Observer Platform</span>
        </div>
    </div>
    
    <script>
        let updateCount = 0;
        
        function updateVisualization() {
            fetch('/api/spectrum')
                .then(response => response.json())
                .then(data => {
                    const plotData = JSON.parse(data.plot);
                    const layout = plotData.layout;
                    const plotDiv = document.getElementById('plot');
                    
                    // Hide loading on first update
                    if (updateCount === 0) {
                        document.getElementById('loading').style.display = 'none';
                    }
                    
                    // Update or create plot
                    if (updateCount === 0) {
                        Plotly.newPlot(plotDiv, plotData.data, layout, {
                            responsive: true,
                            displayModeBar: true,
                            displaylogo: false
                        });
                    } else {
                        Plotly.react(plotDiv, plotData.data, layout);
                    }
                    
                    updateCount++;
                    document.getElementById('update-counter').textContent = 
                        `Updates: ${updateCount}`;
                })
                .catch(error => {
                    console.error('Error updating visualization:', error);
                });
        }
        
        // Initial update
        updateVisualization();
        
        // Auto-update every 500ms
        setInterval(updateVisualization, 500);
        
        // Handle window resize
        window.addEventListener('resize', () => {
            Plotly.Plots.resize(document.getElementById('plot'));
        });
    </script>
</body>
</html>
"""

# Flask application
app = Flask(__name__)
CORS(app)
system = None

@app.route('/')
def index():
    """Serve main interface"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/spectrum')
def get_spectrum():
    """API endpoint for spectrum data"""
    try:
        plot_json = system.get_visualization_data()
        return jsonify({
            'plot': plot_json,
            'status': 'active'
        })
    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def get_status():
    """Get system status"""
    return jsonify({
        'running': system.running,
        'bands': system.config.NUM_BANDS,
        'freq_range': f"{system.config.FREQ_START/1e6:.1f} - {system.config.FREQ_END/1e9:.3f} GHz"
    })


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point"""
    global system
    
    print("=" * 70)
    print("  Vers3Dynamics Search - RF Spectrum Situational Awareness System")
    print("=" * 70)
    print()
    print("  Initializing electromagnetic environment monitoring...")
    print()
    
    # Create system
    system = Vers3DynamicsSearch()
    
    # Start acquisition
    system.start_acquisition()
    
    print(f"  ✓ Spectrum acquisition active")
    print(f"  ✓ Monitoring {system.config.NUM_BANDS} frequency bands")
    print(f"  ✓ Web interface starting on http://localhost:{system.config.PORT}")
    print()
    print("  Opening browser interface...")
    print("  Press Ctrl+C to stop")
    print()
    print("=" * 70)
    
    try:
        # Run Flask app
        app.run(host='0.0.0.0', port=system.config.PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        system.stop_acquisition()
        print("Vers3Dynamics Search terminated.")

if __name__ == '__main__':
    main()
