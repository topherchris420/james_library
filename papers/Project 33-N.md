Project 33-N: Preliminary Multidisciplinary Design
and Embedded Trigger-Timing Evaluation of a
COTS-Based Guided Research Platform
Christopher Woodyard
Vers3Dynamics
R.A.I.N. Lab
christopher@vers3dynamics.com
Abstract—This paper presents a preliminary multidisciplinary
redesign of a commercial-off-the-shelf (COTS)-based guided
research platform incorporating proposed folding-fin kinematics,
deterministic embedded control, edge computation, and radiolog-
ical sensing. The study combines analytical mechanism synthesis,
preliminary structural, aerodynamic, and steady-state thermal
modeling, an edge-inference latency benchmark, and source-
reported electrical trigger-timing measurements. A four-bar
linkage is proposed for fin deployment, with a target deployment
time of 15 ms and a calculated spring-rate target of at least 0.185
N·m/rad. Under the stated assumptions, the hinge-pin model
predicts a factor of safety of 1.88, while the aerodynamic model
places the nominal static margin within the selected preliminary
range near low angle of attack. Across 500 GPIO transitions,
the revised ESP32 high-resolution timer implementation reduced
the reported mean timing error from 2.4 ms to 0.12 ms and
the reported standard deviation from 0.9 ms to 0.03 ms. These
measurements validate only the electrical trigger signal. The
edge-compute benchmark required 1.85 ± 0.15 s for 16 response
tokens and is therefore treated as stationary or ground-side.
Mechanical deployment, dynamic stability, transient thermal
behavior, powered flight, and isotope-classification performance
remain to be validated.
Index Terms—Project 33-N, systems integration, folding-fin
kinematics, embedded timing, edge computing, radiological
sensing, verification and validation
I. INTRODUCTION
Project 33-N investigates whether a compact COTS-based
research platform can combine mechanical deployment, deter-
ministic embedded timing, edge computation, and stationary
radiological-sensing analysis under severe mass, volume, and
power constraints. The present paper is not a flight-readiness,
certification, or operational-capability claim. Its purpose is to
establish a traceable preliminary design record and to separate
analytical, modeled, benchmarked, measured, proposed, and
unvalidated results.
The public Project 33 repository describes a baseline
platform using a three-dimensional-printed airframe, folding
tail fins, and an ESP32-based flight computer [1]. Any guided-
flight result associated with that repository is treated here as
repository-reported background and was not independently
evaluated in this study. The proposed Project 33-N architecture
adds a scintillation-sensing concept and a separate edge-
compute node while intending to retain deterministic command
authority on the microcontroller.
TABLE I
EVIDENCE-STATE DEFINITIONS
State Meaning in this paper
ANALYTICAL Derived from equations, assumptions, or design synthesis.
MODELED Produced by simulation under stated assumptions.
BENCHMARKED Measured for a computing or laboratory condition, not the integrated
system.
MEASURED Observed for a defined electrical or physical subsystem.
PROPOSED Intended architecture or capability not yet demonstrated.
UNVALIDATED No supporting test result is supplied.
ILLUSTRATIVE Conceptual reconstruction, not native engineering evidence.
The baseline design record identifies three principal lim-
itations: 1) thermal-structural vulnerability associated with
polylactic-acid components near the propulsion section; 2)
asymmetric electrical triggering associated with software
scheduling delay; and 3) limited aerodynamic restoring behavior
from flat-plate fins. The redesign addresses these issues
through mechanism synthesis, material substitution, preliminary
multiphysics modeling, and high-resolution timer dispatch.
II. EVIDENCE-STATE FRAMEWORK
To make claim maturity explicit, this paper uses the evidence
states in Table I.
The most defensible present claim is narrow: Project 33-
N establishes a preliminary multidisciplinary design baseline
and a substantially improved source-reported electrical trigger-
timing result. It does not establish physical fin deployment,
flight performance, radiological classification, autonomous
engagement, or integrated operational capability.
III. RELATED WORK
Folding-fin mechanisms may use torsion springs or pyrotech-
nic actuation and can experience rebound or asymmetric de-
ployment [2]. Four-bar linkage synthesis using the Freudenstein
equation provides a deterministic design alternative [3], [7].
In constrained edge computing, QLoRA enables parameter-
efficient model adaptation [9], while low-bit quantization
reduces memory demand. The contribution here is not a new
theory within any single discipline; it is a preliminary evidence-
controlled systems-integration study.


IV. ANALYTICAL MECHANISM DESIGN
A. Four-Bar Linkage Synthesis
ANALYTICAL/PROPOSED: A planar four-bar linkage was
synthesized to move the fin from θ2 = 0◦
to θ2 = 90◦
, with
a target—not measured—deployment time of tdeploy = 15
ms and a nominal 92◦
over-center position. The Freudenstein
relation is
K1 cos θ2 + K2 cos θ4 + K3 = cos(θ2 − θ4), (1)
where K1 = r1/r4, K2 = r1/r2, and
K3 =
r2
1 + r2
2 − r2
3 + r2
4
2r1r2
. (2)
The controlling dimensions are r1 = 30 mm, r2 = 10
mm, r3 = 35 mm, and r4 = 40 mm. The nominal mid-
stroke transmission angle is approximately 45◦
. Physical
deployment time, friction, rebound, locking repeatability, and
synchronization remain unvalidated.
B. Spring-Rate Target
ANALYTICAL: The spring-rate requirement is bounded by
1
2
kθ2
max ≥
1
2
Ifinω2
+
Z θmax
0
Maero(θ) dθ + Edamping, (3)
with the approximate aerodynamic hinge moment
Maero(θ) ≈
1
2
ρv2
Cmα
cSfin sin(2θ). (4)
For the assumed mass, geometry, velocity, and damping inputs,
the calculation gives k ≥ 0.185 N·m/rad. This is a design
target, not an experimentally verified spring rate.
V. MODELED STRUCTURAL, AERODYNAMIC, AND
THERMAL BEHAVIOR
A. Controlling Model Configuration
The manuscript adopts the following controlling preliminary
configuration. The CFD mesh count is fixed at approximately
4.2 million cells; the previously displayed 6.2-million-cell value
is not used in this revision.
• FEA—MODELED: Ansys Mechanical; equivalent 50 g
axial hinge-pin load case; Ti-6Al-4V; nominal 0.5-mm
element size; pin-end constraints; cylindrical-contact load
transfer.
• CFD—MODELED: Ansys Fluent; steady three-
dimensional RANS; k–ω SST; approximately 4.2 million
polyhedral cells; target y+
< 1; domain extending 10
calibers upstream and 20 downstream; Mach 0.25 (80
m/s) at sea level.
• Thermal—MODELED: Steady-state compartment model
using the stated heat-load, ambient, convection, and
material assumptions. Detector integration time, transient
propulsion heating, interface conductance, hot-ambient
cases, and temperature-dependent degradation are outside
the present model.
TABLE II
PROPOSED MATERIAL SUBSTITUTIONS
Component Material Rationale
Airframe Al 7075-T6 Higher strength than PLA
Fins CFRP Reduced aft mass
Hinge pins Ti-6Al-4V High specific strength
AI node ARM SBC Quantized inference host
B. Preliminary Results and Boundaries
MODELED: The hinge-pin model reports a peak von Mises
stress of 468 MPa under the stated equivalent load case.
Relative to an assumed Ti-6Al-4V yield strength of 880
MPa, the modeled factor of safety is 1.88. Native solver files,
load derivation, mesh convergence, contact sensitivity, fatigue,
impact, and temperature-dependent properties are not supplied.
MODELED: The proposed aft-mass reduction moves the
modeled center of gravity forward by approximately 4 mm.
Static margin is
SM =
XCP − XCG
d
. (5)
The predicted static margin lies within the selected 1.5–
2.0-caliber range near the nominal and low-angle-of-attack
condition, but decreases with angle of attack. The result does
not establish dynamic stability.
MODELED: The steady-state thermal model reports a maxi-
mum edge-compute-compartment temperature of approximately
83.7◦
C under a 6.5-W heat load and the selected boundary
conditions. This does not establish transient propulsion-heating
survival or physical thermal correlation.
VI. PROPOSED EDGE-COMPUTE AND
RADIOLOGICAL-SENSING ARCHITECTURE
A. Authority Separation
PROPOSED/UNVALIDATED: A multichannel analyzer would
perform energy binning and peak extraction before formatting
features for the edge-compute node. The current concept uses
an ESP32 for timing-critical state estimation and bounded
control logic, and a Raspberry Pi 5 with 8 GB RAM for
INT4-quantized GGUF inference through llama.cpp.
AI output is advisory only in the proposed architecture. It
is not evidence of direct actuator authority. A complete imple-
mentation must define accepted inputs, permitted outputs, con-
fidence handling, timeout behavior, an “unknown/insufficient
evidence” path, deterministic acceptance logic, safe rejection,
logging, and independent verification that AI output cannot
directly command actuation. Any numerical confidence thresh-
old shown in illustrative material is not calibrated and is not
an operative value.
B. Inference Benchmark
BENCHMARKED: Across N = 50 trials, generation of 16
response tokens after a 64-token prompt required 1.85 ± 0.15
s, corresponding to approximately 8.6 tokens/s; model-loading
time was excluded. Detector acquisition, preprocessing, photon-
integration time, transport, decision logic, and actuation latency


Fig. 1. Evidence-labeled overview. The mechanism panel is analytical/proposed; structural, aerodynamic, static-margin, and thermal panels are illustrative
reconstructions of modeled claims rather than native solver exports; the timer panel summarizes source-reported measured electrical statistics rather than a plot
generated from the raw dataset; and the sensing architecture is proposed and unvalidated. AI output is advisory within the proposed design and remains subject
to deterministic acceptance, safe rejection, and separately governed command authority.
were not included. The result therefore supports only a comput-
ing benchmark and not end-to-end radiological identification.
The present configuration is treated as stationary or ground-
side.
VII. MEASURED ELECTRICAL TRIGGER TIMING
A. Timer Architecture
The baseline firmware used a synchronous loop() structure
and software delays. The revised implementation uses the ESP-
IDF esp_timer API [5], with callback dispatch through a
high-priority FreeRTOS timer task rather than the ordinary
application loop. This paper does not claim formal hard-real-
time guarantees, zero latency, or an “instant” trigger.
B. Source-Reported Measurements
MEASURED/SOURCE-REPORTED: A logic analyzer was used
for N = 500 GPIO transitions [1]. The baseline implementation
reported a mean timing error of 2.4 ms with a standard deviation
Algorithm 1 High-Resolution One-Shot Trigger
Require: trigger_sent = false
1: Configure a one-shot high-resolution timer
2: Register Timer_Deploy_Callback
3: Start the timer using the prescribed delay
4: function Timer_Deploy_Callback(arg)
5: Set the electrical trigger output
6: trigger_sent ← true
7: end function
of 0.9 ms. The revised implementation reported a mean timing
error of 0.12 ms with a standard deviation of 0.03 ms. The
ratios of the rounded values are 20.0× for mean timing error
and 30× for reported standard deviation.
The raw dataset, logic-analyzer model, sampling configu-
ration, timer settings, firmware commit, processor workload,
tail-latency statistics, and independent reproduction were not
supplied with the reviewed package. Consequently, this result


TABLE III
COMPACT CLAIM-TO-EVIDENCE MATRIX
Area State Highest-priority missing evidence
Linkage Analytical /
proposed
Deployment time, friction, rebound, locking, syn-
chronization
Hinge pin Modeled Native model, convergence, fatigue, impact, ther-
mal effects
Aerodynamics Modeled Dynamic derivatives, wind-tunnel correlation, flight
data
Thermal Modeled Transient heating and physical correlation
Edge inference Benchmarked End-to-end latency, calibration, classifier compari-
son
Trigger timing Measured* Raw data, full test configuration, tail latency,
reproduction
Radiological ID Proposed Calibrated spectra, accuracy, false alarms, unknown
handling
Integrated system Unvalidated End-to-end authority, safety, sensing, control, and
flight evidence
*Source-reported electrical measurement.
validates only the source-reported electrical trigger signal and
does not establish physical deployment time, fin synchroniza-
tion, rebound, locking, or flight performance.
VIII. CLAIM-TO-EVIDENCE MATRIX
IX. REPRODUCIBILITY, AVAILABILITY, AND SCOPE
A. Configuration and Reproducibility
The controlling configuration for this revision is the one
stated in the manuscript: 4.2 million CFD cells, the listed 70-
mm-class linkage dimensions, the equivalent 50 g hinge-pin
load case, and the source-reported timing statistics. Future
releases should identify exact geometry revisions, solver
projects, mesh versions, firmware commits, hardware revisions,
prompt templates, quantization settings, sampling parameters,
and statistical scripts.
B. Data and Code Availability
The Project 33 repository is cited in [1], and the referenced
model record is cited in [8]. The raw 500-transition timing
dataset, native FEA/CFD/thermal projects, convergence histo-
ries, detector datasets, and end-to-end test records were not
supplied with this revision and are therefore not available for
independent reproduction through this manuscript.
C. Funding and Conflict of Interest
No external funding is reported for this study. The author
is the founder of Vers3Dynamics, the organization associated
with the platform and software described in this paper.
D. Safety and Dual-Use Scope
This paper documents preliminary research and does not
establish operational readiness, autonomous engagement, flight
certification, safety approval, or legal authorization. The
described radiological-sensing architecture is proposed and
unvalidated. Any physical testing or broader technical disclo-
sure should be conducted only under applicable legal, safety,
range, regulatory, and export-review requirements.
X. LIMITATIONS AND FUTURE WORK
This work does not provide native solver exports, con-
vergence evidence, transient thermal validation, physical
mechanism measurements, powered-flight data, dynamic-
stability measurements, calibrated radiological datasets, isotope-
classification accuracy, or end-to-end system validation. The
next credibility step is a stronger evidence chain rather than a
broader claim: release a reconciled configuration record; publish
native solver outputs and convergence evidence; provide the
raw timing data and reproducible plotting code; test mechanism
deployment, rebound, locking, and synchronization; evaluate
calibrated stationary radiological sensing against conventional
classifiers; and verify the advisory AI authority boundary in
hardware and software.
XI. CONCLUSION
Project 33-N currently supports a preliminary multidisci-
plinary design baseline, a computing-latency benchmark, and
one narrow source-reported electrical timing result. Under the
stated assumptions, the models report a hinge-pin factor of
safety of 1.88, a nominal low-angle static-margin result, and an
83.7◦
C steady-state compartment temperature. Across 500 tran-
sitions, the reported mean electrical timing error decreased from
2.4 ms to 0.12 ms and the reported standard deviation decreased
from 0.9 ms to 0.03 ms. These findings do not establish physical
deployment, flight performance, radiological classification,
autonomous engagement, or integrated operational capability.
Future releases should let traceable, reproducible evidence—
rather than presentation intensity—carry the credibility of the
project.
REFERENCES
[1] C. Woodyard, “Project 33: MANPADS system launcher and rocket
repository,” Vers3Dynamics, 2026. [Online]. Available: https://github.
com/Vers3Dynamics/MANPADS-System-Launcher-and-Rocket
[2] E. L. Fleeman, Tactical Missile Design, 2nd ed. Reston, VA, USA: AIAA,
2006.
[3] R. L. Norton, Design of Machinery, 6th ed. New York, NY, USA:
McGraw-Hill, 2019.
[4] W. D. Callister and D. G. Rethwisch, Materials Science and Engineering:
An Introduction, 10th ed. Hoboken, NJ, USA: Wiley, 2018.
[5] Espressif Systems, “ESP-IDF API reference: high-resolution timers,”
v5.1, 2024.
[6] J. D. Anderson, Fundamentals of Aerodynamics, 6th ed. New York, NY,
USA: McGraw-Hill, 2017.
[7] A. Ghosal, “The Freudenstein equation: design of four-link mechanisms,”
Resonance, vol. 15, no. 8, pp. 699–710, 2010.
[8] C. Woodyard, “Nuclear-Expert-3B,” Hugging Face, 2024. [Online].
Available: https://huggingface.co/Vers3Dynamics/Nuclear-Expert-3B
[9] T. Dettmers, A. Pagnoni, A. Holtzman, and L. Zettlemoyer, “QLoRA:
efficient finetuning of quantized LLMs,” arXiv:2305.14314, 2023.
[10] E. N. Jacobs, K. E. Ward, and R. M. Pinkerton, “The characteristics of
78 related airfoil sections from tests in the variable-density wind tunnel,”
NACA Report 460, 1933.

---
Repository source note: text extracted from the author-supplied PDF with pdftotext -raw. The paper body above is the extracted document, not a rewritten summary.
Record title: Project 33-N: Preliminary Multidisciplinary Design and Embedded Trigger-Timing Evaluation of a COTS-Based Guided Research Platform
