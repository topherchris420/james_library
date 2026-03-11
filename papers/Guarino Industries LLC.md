The Guarino Similarity Metric Brian Guarino Guarino Industries LLC,
Raleigh, NC, United States (Dated: 11 February 2026) Engineering systems
that strongly couple thermal transport, electromagnetic forcing, fluid
motion, and struc- tural response resist evaluation by traditional
single-domain performance metrics. Measures such as thrust- to-weight
ratio, specific power, or thermal efficiency isolate individual
subsystems, thereby obscuring the cross-domain penalties and synergies
that dominate system-level behavior in advanced operating regimes. This
paper introduces the Guarino Similarity Metric (ΨG), a rigorously
dimensionless comparison frame- work constructed from physically
interpretable similarity groups. The metric evaluates the ratio of
functional driving potential to unavoidable systemic penalties,
including resistive decay, radiative loss, compressibility effects, and
structural utilization constraints that arise in high-energy
magnetohydrodynamic (MHD) fluid systems and hypersonic environments. By
enforcing dimensional invariance and scale independence, the Guarino
Similarity Metric enables architecture-level ranking of integrated
systems under identical boundary conditions without claiming predic-
tive authority over absolute performance. A worked quantitative example
demonstrates that system architec- tures with lower raw driving
potential may achieve superior functional density when dominant
thermodynamic and magnetohydrodynamic losses are minimized. Keywords:
similarity theory, dimensional analysis, multi-physics systems,
magnetohydrodynamics, functional density, hypersonic propulsion I.
INTRODUCTION Modern engineering platforms increasingly operate in
regimes where thermal energy transport, electromagnetic forcing, fluid
dynamics, and structural constraints are tightly coupled. Examples
include high-power electrome- chanical drives, magnetohydrodynamic (MHD)
propul- sion concepts, plasma actuators, and advanced fusion containment
architectures. In such regimes, subsystem- isolated metrics fail to
capture dominant cross-domain interactions. For instance, increasing
electromagnetic forcing often incurs non-linear thermal management mass
penalties or resistive dissipation that reduce net system utility. This
work introduces the Guarino Similarity Met- ric (ΨG), a nondimensional
comparison index intended not to govern system dynamics, but to rank
architec- tures according to how effectively they convert func- tional
potential into useful physical work while account- ing for unavoidable
penalties. Unlike predictive solvers (CFD/FEA), ΨG is a scaling tool for
early-stage trade studies, ensuring that design choices account for
multi- physics closure. II. THEORETICAL FORMULATION The formulation of
ΨG is grounded in classical simi- larity theory and the Buckingham π
theorem1. While canonical dimensionless numbers (e.g., Reynolds, Nus-
selt, Hartmann) quantify isolated physical mechanisms, they do not
inherently compare integrated architectures. ΨG assembles these
interpretable similarity groups into a single normalized index. A.
General Definition The Guarino Similarity Metric is defined as the ratio
of the product of dimensionless Driver Groups (Πdriver) to the product
of dimensionless Penalty Groups (Πpenalty ) evaluated at a specific
operating point O: ΨG(O) = Q Πdrivers Q Πpenalties (1) where the
numerator denotes the product of all driver groups and the denominator
denotes the product of all penalty groups. Expanding into its
constituent groups, including terms for resistive, radiative, and
compressibility effects: ΨG = Πth · ΠEM · Πβ Πμ · Πv · Πα · Πσ · Πρ · ΠR
· Πη · Πrad · Πc (2) Where all Π terms are nondimensional by
construction. The metric effectively represents a measure of func-
tional density: high values indicate architectures where a greater
fraction of system mass and volume participates in recoverable physical
work, rather than serving as dead mass or managing losses. B. Conditions
of Validity (The Completeness Coefficient) To ensure the metric captures
the necessary physics for a given regime, we introduce the Completeness
Coef- ficient, CG ∈ \[0, 1\]. Numerical evaluation of ΨG is con- sidered
valid only when: 2 CG ≥ 0.8 (3) Systems below this threshold are
classified as unclosed, indicating that significant cross-domain
couplings (e.g., ignoring radiative cooling in a vacuum environment)
have been omitted. This restriction prevents numerical rank- ings that
omit dominant physical couplings relevant to the declared operating
regime. III. DEFINITION OF SIMILARITY GROUPS The characteristic velocity
used throughout is defined as u = ˙m/(ρAc). A. Driver Groups (Numerator)
Driver groups represent recoverable functional poten- tial. • Thermal
Driving Potential (Πth): Πth = cp∆T u2 (4) This represents the ratio of
recoverable thermal en- thalpy to kinetic energy. It is inversely
related to the Eckert number. • Electromagnetic Forcing Strength (ΠEM ):
ΠEM = BJL ρu2 (5) This term compares the Lorentz body force to inertial
resistance. It is physically analogous to the Stuart Number (Interaction
Parameter) in MHD flows2, representing the dominance of mag- netic
forces over fluid inertia. • Ballistic Similarity (Πβ ): Πβ = β ρenv Da
(6) Normalizes momentum-retention capability against environmental
density, valid for continuum aerody- namic regimes. Where possible,
similarity groups are expressed in forms directly analogous to canon-
ical nondimensional numbers to preserve inter- pretability. B. Penalty
Groups (Denominator) Penalty groups represent losses, constraints, and
inef- ficiencies. • Viscous Loss (Πμ): Πμ = μ ρuDh = 1 Re (7) Represents
momentum diffusion relative to inertial transport (Inverse Reynolds
Number). • Resistive Decay (Πη ): Πη = η μ0uL = 1 Rem (8) Represents
magnetic diffusion relative to advection (Inverse Magnetic Reynolds
Number). High values indicate the magnetic field leaks out of the fluid
faster than it can drive it, a critical loss in plasma actuators. •
Radiative Loss (Πrad): Πrad = σSB ϵT 4L ρu3 (9) Represents the ratio of
radiative power loss to ki- netic energy flux (Boltzmann Number). This
term is dominant in high-temperature vacuum applica- tions. •
Compressibility / Wave Drag (Πc): Πc = u a = M a (10) The Mach number.
As Πc → 1 (transonic) or Πc \> 1 (hypersonic), shock wave formation in-
troduces severe entropy penalties that are distinct from viscous losses.
• Volatility / Cavitation Proximity (Πv ): Πv = Pv ρu2 (11) Indicates
proximity to phase instability (cavitation or flash evaporation) under
dynamic pressure. • Structural Stress Utilization (Πσ ): Πσ = σskin
σallow (12) Measures the proximity of the material system to its failure
limit. A value approaching 1.0 indicates a highly optimized structure;
lower values indicate conservative, heavy design. • Structural Mass
Penalty (Πρ): Πρ = ρcomp ρref (13) Measures the effective mass penalty
associated with material and structural choices relative to a refer-
ence system. Values of Πρ \> 1.0 indicate increased parasitic
(non-participating) mass for a given func- tional volume, while values
near unity indicate par- ity with the reference design. 3 • Thermal
Expansion Strain (Πα): Πα = αef f ∆T (14) Quantifies thermally induced
geometric distortion. • Thermal Inefficiency (ΠR): ΠR = Rth Rref (15)
Represents losses due to imperfect thermal cou- pling. IV. WORKED
QUANTITATIVE EXAMPLE To demonstrate the comparative utility of ΨG, two
candidate architectures (Architecture A and Architecture B) are
evaluated under identical boundary conditions. Representative values are
chosen to be physically plausi- ble for compressible MHD regimes and are
not intended to represent a specific flight or reactor design. •
Architecture A: Characterized by high raw elec- tromagnetic forcing but
poor confinement (high re- sistive decay) and significant radiative
losses. • Architecture B: Characterized by lower peak forcing but highly
integrated confinement (low re- sistive decay) and optimized thermal
recycling. A. Dimensionless Group Values The following values are drawn
from representative ranges for compressible magnetohydrodynamic (MHD)
regimes. TABLE I. Dimensionless Group Values for Comparative Anal- ysis
Group Symbol Arch. A Arch. B Drivers Thermal Potential Πth 2200 1800 EM
Forcing ΠEM 1.2 0.7 Ballistic Similarity Πβ 4200 3200 Penalties Viscous
Loss Πμ 8.0 × 10−6 3.0 × 10−6 Resistive Decay Πη 0.20 0.05 Radiative
Loss Πrad 0.50 0.15 Compressibility Πc 0.90 0.60 Volatility Πv 0.18 0.08
Thermal Strain Πα 0.003 0.002 Stress Utilization Πσ 0.85 0.55 Mass
Penalty Πρ 1.3 1.3 Thermal Inefficiency ΠR 1.6 1.1 B. Computation and
Ranking Substituting these values into Eq. 2: Architecture A: ΨG,A ≈
3.01 × 1016 (16) Architecture B: ΨG,B ≈ 3.25 × 1018 (17) C.
Interpretation of Results Despite Architecture A possessing
significantly higher driver terms (higher Πth and ΠEM ), Architecture B
achieves a ΨG score approximately 100 times higher. ΨG,B ΨG,A ≈ 107.9
(18) This ranking reflects that Architecture B minimizes the critical
high-energy penalties---specifically Resistive Decay (Πη ) and Radiative
Loss (Πrad)---which dominate performance in this regime. Architecture A,
while pow- erful, loses the majority of its potential to magnetic dif-
fusion and blackbody radiation. V. CONCLUSION The Guarino Similarity
Metric provides a mathemat- ically consistent framework for comparing
integrated multi-physics systems where single-domain metrics fail. By
explicitly defining the ratio of Drivers to Penal- ties---now including
resistive, radiative, and compress- ibility terms---ΨG helps expose the
hidden costs of sub- systems that appear high-performance when evaluated
in isolation. The metric is scale-independent and adapt- able, making it
a robust tool for early-stage architectural down-selection in advanced
aerospace and magnetohy- drodynamic applications. NOMENCLATURE ΨG:
Guarino Similarity Metric Πth: Thermal driving potential ΠEM :
Electromagnetic forcing strength Πβ : Ballistic similarity group Πμ:
Viscous loss penalty Πη : Resistive decay penalty Πrad: Radiative loss
penalty 4 Πc: Compressibility (Mach number) penalty Πv : Volatility /
cavitation proximity penalty Πσ : Structural stress utilization Πρ:
Structural mass (density) penalty ΠR: Thermal inefficiency penalty u:
Characteristic velocity ˙m: Mass flow rate Ac: Characteristic flow area
L: Characteristic length Dh: Hydraulic diameter ρ: Fluid density ρref:
Reference density ρcomp: Effective composite/system density ρenv:
Environmental density cp: Specific heat at constant pressure ∆T :
Characteristic temperature difference Rth: Effective thermal resistance
Rref: Reference thermal resistance αeff: Effective coefficient of
thermal expansion B: Magnetic flux density J: Current density η:
Electrical resistivity μ0: Magnetic permeability of free space μ:
Dynamic viscosity σallow: Allowable material stress σskin: Applied
structural stress ϵ: Effective emissivity σSB : Stefan--Boltzmann
constant a: Speed of sound Ma: Mach number Pv : Vapor pressure β:
Ballistic momentum parameter 1E. Buckingham, Phys. Rev. 4, 345 (1914).
2P. A. Davidson, An Introduction to Magnetohydrodynamics (Cambridge
University Press, 2001). 3G. I. Barenblatt, Scaling, Self-Similarity,
and Intermediate Asymptotics (Cambridge University Press, 1996). 4F. P.
Incropera et al., Fundamentals of Heat and Mass Transfer (Wiley, 7th
ed.). 5F. M. White, Fluid Mechanics (McGraw-Hill, 8th ed.).
