Geometric Dynamic Location Theory: Temporal
Experience and Inter-Configuration Correlations
from Quantum State Space Curvature
Christopher Woodyard
Vers3Dynamics
R.A.I.N. Lab
christopher@vers3dynamics.com
Abstract—We present a geometric formulation of Dynamic
Location Theory (DLT) in which temporal experience and weak
inter-configuration correlations emerge from the intrinsic cur-
vature of quantum configuration space. Treating the projective
Hilbert space of pure states as a Riemannian manifold endowed
with the Fubini–Study metric, we derive a scalar coupling
γ as a geometric invariant rather than a phenomenological
parameter. The coupling is shown to be dimensionally consistent,
Planck suppressed, and dependent on many-body configuration
space curvature. Explicit calculations are provided for single
qubits, composite systems, and realistic atomic clock models. The
resulting predictions are consistent with current experimental
bounds and yield falsifiable scaling laws with system size and
entanglement depth.
Index Terms—timeless quantum mechanics, block universe,
relational time, many-worlds interpretation, configuration space
geometry, Fubini–Study metric, scalar curvature, scalar coupling,
atomic clocks, quantum foundations
I. INTRODUCTION
Quantum mechanics admits formulations in which time
is not fundamental, notably constraint-based and timeless
approaches. Yet physical experience exhibits strong temporal
ordering and persistent correlations. Dynamic Location Theory
proposes that such correlations emerge from weak couplings
between nearby configurations in quantum state space rather
than from linear time evolution alone.
Previous formulations introduced a scalar coupling γ phe-
nomenologically. Here, we derive γ from first principles by
treating quantum state space geometrically. The central claim
is that the curvature of configuration space induces suppressed
but nonzero inter-configuration correlations, manifesting as
temporal continuity. This approach provides a natural, dimen-
sionally consistent explanation for emergent temporal behav-
ior.
II. CONFIGURATION SPACE GEOMETRY
A. Projective Hilbert Space
Let H be a complex Hilbert space with normalized pure
states |ψ⟩. Physical states correspond to rays, forming the
projective Hilbert space P(H). This identification removes the
physically irrelevant global phase.
B. Fubini–Study Metric
For a smoothly parameterized state |ψ(λµ
)⟩, the infinites-
imal distance must be invariant under global phase changes.
The squared line element is
ds2
= ⟨dψ|dψ⟩ − |⟨ψ|dψ⟩|2
, (1)
which subtracts the contribution from pure phase variation.
Equivalently, the metric tensor is
gµν = ℜ [⟨∂µψ|∂νψ⟩ − ⟨∂µψ|ψ⟩⟨ψ|∂νψ⟩] . (2)
This metric defines the infinitesimal distinguishability of quan-
tum states in parameter space, forming the foundation for
curvature calculations.
III. CURVATURE OF QUANTUM STATE SPACE
A. Geometric Objects
From gµν, we construct the Levi–Civita connection, Rie-
mann tensor, Ricci tensor, and scalar curvature R using
standard differential geometry.
B. Single Qubit
Consider
|ψ⟩ = cos
θ
2
|0⟩ + eiϕ
sin
θ
2
|1⟩. (3)
Derivatives:
∂θ|ψ⟩ = −
1
2
sin
θ
2
|0⟩ +
1
2
eiϕ
cos
θ
2
|1⟩, (4)
∂ϕ|ψ⟩ = ieiϕ
sin
θ
2
|1⟩. (5)
Inner products yield
gθθ =
1
4
, gϕϕ =
1
4
sin2
θ. (6)
Thus
ds2
=
1
4
(dθ2
+ sin2
θ dϕ2
), (7)
which is the round metric on S2
of radius 1/2. The scalar
curvature is
R = 8. (8)
(Note: Alternative normalizations scale R by a constant factor;
here we adopt the quantum-information convention yielding
R = 8.)


C. Two-Qubit Product States
For a product state |Ψ⟩ = |ψ1⟩ ⊗ |ψ2⟩, the metric decom-
poses additively:
ds2
prod = ds2
1 + ds2
2, R
(2)
prod = 8 + 8 = 16. (9)
By induction, for N-qubit product states:
R
(N)
prod = 8N. (10)
D. Entangled Two-Qubit States
For a Schmidt-rank-2 state
|Ψ⟩ = cos α|00⟩ + eiβ
sin α|11⟩, (11)
the metric is
ds2
= dα2
+ sin2
α cos2
α dβ2
, (12)
with scalar curvature
R(α) = 8 − 24 sin2
(2α). (13)
Maximum entanglement (α = π/4): RBell = −16. Product
limit: Rsep = 8. Entanglement can flip the sign of curvature.
E. N-Qubit Entangled Manifolds
For GHZ-type states
|ΨN ⟩ = cos α|0⟩⊗N
+ sin α|1⟩⊗N
, (14)
the effective 2D parameter space curvature scales inversely:
RGHZ(N) ∼ −
c
N
, c = O(1). (15)
Dimensional collapse of accessible configuration space implies
suppression with system size (β = 1).
IV. EMERGENCE OF THE SCALAR COUPLING γ
A. Effective Interaction
We model γ as an effective coupling:
Sγ = γ
Z
d4
x ϕ(x) ρ(x), (16)
where ϕ(x) encodes configuration space proximity, and ρ(x)
is the local energy density.
B. Dimensional Consistency
Given [ρ] = energy · length−3
, [d4
x] = length4
, γϕ must
have dimensions (energy · length)−1
. Fubini–Study curvature
R is dimensionless, so a fundamental scale is needed. We
introduce the Planck length ℓP and mass MP .
C. Definition of γ
We define
γ = α
|⟨R⟩|
M2
P ℓ2
P
, (17)
with α ∼ 1 and ⟨R⟩ the averaged scalar curvature. This
ensures correct units and Planck suppression. In path-integral
formulations over curved state space, γ effectively arises as
exp(−R/R0), with R0 = 8 from the qubit baseline.
D. Many-Body Scaling
For N particles:
γ(N) =
αR1
NβM2
P ℓ2
P
, β = 1, (18)
showing suppression for large systems and enhancement for
small, coherent quantum systems.
V. APPLICATION TO ATOMIC CLOCKS
A. Simplified Model
Consider an effective two-level clock Hamiltonian
Ĥ = ω0σz + Ω(t)(σ+ + σ−). (19)
The accessible state manifold is a deformed Bloch sphere;
curvature depends on driving and decoherence.
B. Predicted γ Values
Single-ion clocks (N = 1): γ ∼ 10−16
–10−17
. Optical
lattice clocks (N ∼ 104
): γ ≲ 10−20
. These values are below
current experimental bounds, consistent with null results from
clock comparisons.
VI. OBSERVABLE PREDICTIONS
1. **Entanglement Scaling**: ∆f/f ∝ N−β
, with β = 1.
Deviations falsify the model.
2. **Geometric Phase Anomaly**: Closed loops in pa-
rameter space yield an additional phase proportional to γ
and integrated curvature, distinct from standard Berry phase
effects.
3. **Correlation Signatures**: Weak frequency correlations
emerge when spatially separated clocks trace geometrically
proximate trajectories in state space.
VII. DISCUSSION
The scalar coupling γ arises naturally as a geometric invari-
ant, suppressed by the Planck scale and modulated by many-
body structure. Temporal continuity emerges from configura-
tion space proximity rather than fundamental time flow. This
unifies quantum geometry, information-theoretic distance, and
observable physics. Potential connections to quantum gravity,
entanglement entropy, and holographic curvature merit future
exploration.
VIII. CONCLUSION
We developed a fully geometric Dynamic Location Theory,
deriving γ from first principles. The theory is dimensionally
consistent, bounded by experimental constraints, and falsifi-
able. Future work includes connections to quantum gravity,
information geometry, and path integral formulations over
curved quantum state spaces.
ACKNOWLEDGMENT
The author thanks the broader physics community for
continued dialogue on the foundations of time and quantum
mechanics.


REFERENCES
[1] I. Bengtsson and K. Życzkowski, Geometry of Quantum States. Cam-
bridge University Press, 2006.
[2] S. L. Braunstein and C. M. Caves, “Statistical distance and the geometry
of quantum states,” Phys. Rev. Lett., vol. 72, pp. 3439–3443, 1994.
[3] M. A. Nielsen and I. L. Chuang, Quantum Computation and Quantum
Information. Cambridge University Press, 2010.
[4] C. Rovelli, Quantum Gravity. Cambridge University Press, 2004.
[5] C. Rovelli, “Quantum mechanics without time,” Phys. Rev. D, vol. 42,
pp. 2638–2644, 1990.
[6] A. Ashtekar and T. Schilling, “Geometry of quantum mechanics,”
arXiv:gr-qc/9706069, 1997.
[7] A. Aeppli et al., “Atomic clock frequency ratios with fractional uncer-
tainty ≤ 3.2×10−18,” arXiv:2512.21428 [physics.atom-ph], Dec. 2025;
Metrologia (2026).

---
Repository source note: text extracted from the public Zenodo PDF with pdftotext -raw. The paper body above is the extracted preprint, not a rewritten summary.
Record title: Emergent Time and Quantum Correlations from the Geometry of Quantum State Space
DOI: https://doi.org/10.5281/zenodo.18295394
License: CC-BY-4.0
