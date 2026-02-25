# -*- coding: utf-8 -*-
"""Resonance / scalar-field / RLC circuit logic.

Standalone module — does **not** depend on hello_os.core.
Extracted from the *RLC Explorer* section of hello_os.py.
"""

import numpy as np

__all__ = [
    "skin_depth",
    "ac_resistance",
    "core_loss_factor",
    "nonlinear_inductance",
    "dL_di",
    "parasitic_capacitance",
    "dielectric_absorption",
    "calculate_poles",
    "enhanced_rk4_solution",
    "analytic_solution",
    "auto_time_scale",
    "RLC_PRESETS",
]


# ============================================================================
# Material / electromagnetics helpers
# ============================================================================


def skin_depth(freq, conductivity=5.96e7):
    """Calculate skin depth for copper at *freq* Hz."""
    mu0 = 4 * np.pi * 1e-7
    if freq < 1:
        return 1e10  # DC case
    return np.sqrt(2 / (2 * np.pi * freq * mu0 * conductivity))


def ac_resistance(R_dc, freq, wire_radius=1e-3):
    """Frequency-dependent resistance due to skin effect."""
    if freq < 100:
        return R_dc
    delta = skin_depth(freq)
    ratio = wire_radius / delta
    if ratio < 0.1:
        return R_dc
    return R_dc * (1 + 0.1 * np.sqrt(ratio))


def core_loss_factor(freq, flux_density, steinmetz_k=0.05, alpha=1.6, beta=2.0):
    """Core losses in magnetic materials (Steinmetz equation)."""
    if freq < 1:
        return 0
    return steinmetz_k * (freq / 1000) ** alpha * flux_density ** beta


def nonlinear_inductance(i, L0, Isat):
    """Realistic inductor saturation with smooth transition."""
    return L0 / (1.0 + (i / Isat) ** 2)


def dL_di(i, L0, Isat):
    """Derivative of nonlinear inductance for numerical solver."""
    denom = 1.0 + (i / Isat) ** 2
    return -2.0 * L0 * i / (Isat ** 2 * denom ** 2)


def parasitic_capacitance(L, wire_turns=10):
    """Estimate parasitic capacitance in inductor (farads)."""
    return max(0.5e-12, L * 1e-6 * wire_turns * 0.1)


def dielectric_absorption(C, V, tau_da=0.001):
    """Capacitor dielectric absorption effect — returns additional charge."""
    return C * V * 0.02 * (1 - np.exp(-tau_da))


def calculate_poles(C, L, R_total):
    """Calculate characteristic poles for damping analysis.

    Returns ``(s1, s2)`` — may be complex.
    """
    alpha = R_total / (2.0 * L)
    omega0 = 1.0 / np.sqrt(L * C)
    disc = alpha ** 2 - omega0 ** 2
    if disc >= 0:
        s1 = -alpha + np.sqrt(disc)
        s2 = -alpha - np.sqrt(disc)
    else:
        omegad = np.sqrt(-disc)
        s1 = -alpha + 1j * omegad
        s2 = -alpha - 1j * omegad
    return s1, s2


# ============================================================================
# Numerical solver
# ============================================================================


def enhanced_rk4_solution(
    C, L0, R_dc, V0, t, Isat, enable_realism, ESR, proximity_factor=1.0
):
    """RK4 solver with optional real-world effects.

    Parameters
    ----------
    enable_realism : dict
        Keys: ``saturation``, ``skin_effect``, ``core_loss``,
        ``dielectric``, ``parasitic``.
    """
    dt = t[1] - t[0]
    v = np.zeros(len(t))
    i_arr = np.zeros(len(t))
    v[0] = V0

    C_parasitic = parasitic_capacitance(L0) if enable_realism.get("parasitic") else 0
    C_total = C + C_parasitic

    for k in range(len(t) - 1):
        vk, ik = v[k], i_arr[k]

        if k > 2:
            freq_est = (
                abs(ik - i_arr[k - 1]) / (dt * max(abs(ik), 1e-6)) / (2 * np.pi)
            )
        else:
            freq_est = 1.0 / (2 * np.pi * np.sqrt(L0 * C_total))

        def _derivs(vv, ii):
            if enable_realism.get("saturation"):
                L_eff = nonlinear_inductance(ii, L0, Isat)
                dL = dL_di(ii, L0, Isat)
            else:
                L_eff = L0
                dL = 0

            if enable_realism.get("skin_effect"):
                R_ac = ac_resistance(R_dc, freq_est) * proximity_factor
            else:
                R_ac = R_dc

            R_tot = R_ac + ESR

            if enable_realism.get("core_loss") and abs(ii) > 1e-6:
                flux_density = L_eff * abs(ii) / 1e-4
                R_tot += core_loss_factor(freq_est, flux_density)

            if enable_realism.get("dielectric"):
                v_offset = dielectric_absorption(C_total, vv, dt) / C_total
                vv = vv - v_offset * 0.1

            denom = (L_eff + ii * dL) if enable_realism.get("saturation") else L_eff
            denom = max(denom, L_eff * 0.1)

            dvdt = -ii / C_total
            didt = -(R_tot * ii + vv) / denom
            return dvdt, didt

        dv1, di1 = _derivs(vk, ik)
        dv2, di2 = _derivs(vk + 0.5 * dt * dv1, ik + 0.5 * dt * di1)
        dv3, di3 = _derivs(vk + 0.5 * dt * dv2, ik + 0.5 * dt * di2)
        dv4, di4 = _derivs(vk + dt * dv3, ik + dt * di3)

        v[k + 1] = vk + (dt / 6) * (dv1 + 2 * dv2 + 2 * dv3 + dv4)
        i_arr[k + 1] = ik + (dt / 6) * (di1 + 2 * di2 + 2 * di3 + di4)

    return v, i_arr


# ============================================================================
# Analytic solution (linear case)
# ============================================================================


def analytic_solution(C, L, R_total, V0, t):
    """Closed-form RLC solution.  Returns ``(v, i, regime_str)``."""
    alpha = R_total / (2.0 * L)
    omega0 = 1.0 / np.sqrt(L * C)
    disc = omega0 ** 2 - alpha ** 2

    if disc > 1e-9:
        omegad = np.sqrt(disc)
        i_arr = (V0 / (L * omegad)) * np.exp(-alpha * t) * np.sin(omegad * t)
        v = V0 * np.exp(-alpha * t) * (
            np.cos(omegad * t) + (alpha / omegad) * np.sin(omegad * t)
        )
        regime = "Underdamped"
    elif disc < -1e-9:
        s1 = -alpha + np.sqrt(alpha ** 2 - omega0 ** 2)
        s2 = -alpha - np.sqrt(alpha ** 2 - omega0 ** 2)
        A = V0 / (L * (s1 - s2))
        i_arr = A * (np.exp(s1 * t) - np.exp(s2 * t))
        di_dt = A * (s1 * np.exp(s1 * t) - s2 * np.exp(s2 * t))
        v = V0 - L * di_dt - R_total * i_arr
        regime = "Overdamped"
    else:
        i_arr = (V0 / L) * t * np.exp(-alpha * t)
        di_dt = (V0 / L) * np.exp(-alpha * t) * (1 - alpha * t)
        v = V0 - L * di_dt - R_total * i_arr
        regime = "Critically Damped"

    return v, i_arr, regime


# ============================================================================
# Helpers
# ============================================================================


def auto_time_scale(C, L):
    """Return ``(t_max, scale_factor, unit_label)``."""
    tau = np.sqrt(L * C)
    t_max = max(12 * tau, 100e-6)
    if t_max < 1e-3:
        return t_max, 1e6, "µs"
    if t_max < 1:
        return t_max, 1e3, "ms"
    return t_max, 1, "s"


# ============================================================================
# Built-in presets
# ============================================================================

RLC_PRESETS = {
    "Camera Flash": {
        "C": 330e-6, "L": 0.5e-3, "R": 5, "ESR": 0.2, "V0": 300,
        "Proximity": 1.2,
    },
    "Spark-Gap Radio": {
        "C": 1e-9, "L": 10e-6, "R": 50, "ESR": 0.01, "V0": 1000,
        "Proximity": 1.5,
    },
    "Tesla Primary": {
        "C": 20e-9, "L": 50e-6, "R": 1, "ESR": 0.01, "V0": 10000,
        "Proximity": 1.8,
    },
    "LC Tank (HF)": {
        "C": 100e-12, "L": 1e-6, "R": 10, "ESR": 0.0, "V0": 5,
        "Proximity": 2.0,
    },
    "Power Supply": {
        "C": 1000e-6, "L": 5e-3, "R": 1, "ESR": 0.5, "V0": 50,
        "Proximity": 1.1,
    },
}
