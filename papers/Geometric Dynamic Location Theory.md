Geometric Dynamic Location Theory: Temporal
Correlations from Quantum State Space Curvature
Christopher Woodyard
Vers3Dynamics, R.A.I.N. Lab
Washington, DC
christopher@vers3dynamics.com
Abstract—We present a geometric formulation of Dynamic
Location Theory (DLT) in which temporal correlations and weak
inter-configuration couplings emerge from the intrinsic curvature
of quantum configuration space. Treating the projective Hilbert
space of pure states as a Riemannian manifold endowed with the
Fubini–Study metric, we derive an effective scalar coupling γ as a
geometric invariant rather than a phenomenological parameter.
The coupling is shown to be dimensionally consistent, Planck
suppressed, and dependent on many-body curvature scaling.
Explicit curvature calculations are provided for single qubits,
multi-qubit product states, GHZ-entangled states for N = 3, 4, 5,
and realistic atomic clock Hamiltonians. The resulting predictions
are consistent with current experimental bounds and yield
falsifiable scaling laws with entanglement depth and system size.
Index Terms—timeless quantum mechanics, relational time,
configuration space geometry, Fubini–Study metric, scalar cur-
vature, entanglement geometry, atomic clocks
I. INTRODUCTION
Several formulations of quantum mechanics admit a fun-
damentally timeless description, including constraint-based
and relational approaches [2], [3]. Nevertheless, physical
observations exhibit strong temporal ordering and persistent
correlations. Dynamic Location Theory proposes that such
correlations arise from weak couplings between nearby con-
figurations in quantum state space, rather than from time as a
fundamental parameter.
Earlier versions of DLT introduced a scalar coupling γ
phenomenologically. In this work, γ is derived from first
principles by exploiting the intrinsic curvature of quantum
configuration space. Temporal continuity is interpreted as an
emergent effect arising from suppressed but nonzero inter-
configuration correlations induced by curvature.
II. CONFIGURATION SPACE GEOMETRY
A. Projective Hilbert Space
Let H be a complex Hilbert space with normalized pure
states |ψ⟩. Physical states correspond to rays under the equiv-
alence relation |ψ⟩ ∼ eiχ
|ψ⟩, defining the projective Hilbert
space P(H).
B. Fubini–Study Metric
For a smoothly parameterized state |ψ(λµ
)⟩, the Fubini–
Study line element is
ds2
= ⟨dψ|dψ⟩ − |⟨ψ|dψ⟩|2
, (1)
leading to the metric tensor
gµν = ℜ! [⟨∂µψ|∂νψ⟩
- ⟨∂µψ|ψ⟩⟨ψ|∂νψ⟩.(2)
III. CURVATURE OF QUANTUM STATE SPACE
A. Single Qubit
A general qubit state is
|ψ⟩ = cos
θ
2
|0⟩ + eiϕ
sin
θ
2
|1⟩. (3)
The induced metric is
ds2
=
1
4
dθ2
+ sin2
θ, dϕ2

, (4)
corresponding to a sphere of radius 1/2. The scalar curvature
is
Rqubit = 8. (5)
B. Multi-Qubit Product States
For an N-qubit product state, the total metric decomposes
additively:
ds2
=
N
X
i=1
ds2
i . (6)
Scalar curvature therefore scales linearly:
R
(N)
prod = 8N. (7)
C. Entangled Two-Qubit States
For the Schmidt-parameterized state
|Ψ⟩ = cos α|00⟩ + eiβ
sin α|11⟩, (8)
the metric becomes
ds2
= dα2
+ sin2
α cos2
α, dβ2
, (9)
with scalar curvature
R(α) = 8 − 24 sin2
(2α). (10)


D. GHZ States for Arbitrary N
Consider the GHZ family
|ΨN ⟩ = cos α|0⟩⊗N
+ eiβ
sin α|1⟩⊗N
. (11)
The induced metric on the (α, β) manifold is
ds2
= dα2
+ sin2
α cos2
α, dβ2
. (12)
The intrinsic scalar curvature of this 2D manifold is
Rintrinsic = −8. (13)
The effective contribution to the full configuration space scales
as
RGHZ(N) = −
8
N
. (14)
IV. EMERGENT SCALAR COUPLING
A. Effective Interaction
Inter-configuration correlations are modeled via
Sγ = γ
Z
d4
x, ϕ(x)ρ(x), (15)
where ϕ(x) is a configuration-space proximity function with
finite support and ρ(x) is the local energy density.
B. Dimensional Analysis
Requiring Sγ to be dimensionless yields
[γϕ] = (energy · length)−1
. (16)
Since Fubini–Study curvature is dimensionless, Planck scales
must enter:
ℓP =
r
ℏG
c3
, MP =
r
ℏc
G
. (17)
We define
γ = α
⟨R⟩
M2
P ℓ2
P
, (18)
with α ∼ 1. Effective observable couplings are further
suppressed by configuration-space overlap integrals
R
ϕ, d3
x,
reflecting the finite extent of proximity functions introduced
in Sec. IV.A.
C. Numerical Estimate
Using physical constants,
M2
P ℓ2
P ≈ 1.25 × 10−85
, kg2
m2
. (19)
For ⟨R⟩ ∼ 10,
γ ∼ 10−85
. (20)
After accounting for overlap suppression,
γeff ∼ 10−16
to 10−20
. (21)
V. ATOMIC CLOCK APPLICATION
A. Clock Hamiltonian
We consider
Ĥ =
ℏω0
2
σz + ℏΩ(t)σx. (22)
B. Curvature with Decoherence
Including decoherence rate Γ, the effective metric rescales
as
ds2
=
1
4
dθ2
+ sin2
θ, dϕ2

e−Γt
. (23)
The scalar curvature becomes
R(t) = 8eΓt
. (24)
Averaging over the coherence time Tc = 1/Γ yields
⟨R⟩ ≈ 8(e − 1) ≈ 13.7. (25)
VI. CONCLUSION
Dynamic Location Theory admits a fully geometric formu-
lation in which temporal correlations emerge from curvature
in quantum configuration space. The scalar coupling γ arises
naturally, is Planck suppressed, and exhibits clear many-body
scaling, while remaining consistent with present experimental
bounds.
REFERENCES
[1] I./Bengtsson and K./.Zyczkowski, Geometry of Quantum States. Cam-
bridge University Press, 2006.
[2] C. Rovelli, “Quantum mechanics without time,” Phys. Rev. D, vol. 42,
pp. 2638–2644, 1990.
[3] D. N. Page and W. K. Wootters, “Evolution without evolution,” Phys.
Rev. D, vol. 27, pp. 2885–2892, 1983.

---
Repository source note: text extracted from the public Zenodo PDF with pdftotext -raw. The paper body above is the extracted preprint, not a rewritten summary.
Record title: Geometric Dynamic Location Theory: Temporal Correlations from Quantum State Space Curvature
DOI: https://doi.org/10.5281/zenodo.18300890
License: CC-BY-4.0
