import numpy as np
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt

def fit_pt2_from_samples(data, plot=True):
# 1) extract the step‐window
    samples = [s for s in data["samples"] if data["T1"] <= s["timestamp"] <= data["T2"]]
    t = np.array([s["timestamp"] - data["T1"] for s in samples])
    hr = np.array([s["hr"] for s in samples])
    hr0 = hr[0]
    hr_step = hr - hr0

    # 2) PT2 model
    def pt2(t, K, wn, zeta):
        if zeta >= 1:
            s1 = -wn*(zeta - np.sqrt(zeta**2-1))
            s2 = -wn*(zeta + np.sqrt(zeta**2-1))
            A = K * s2/(s2-s1)
            B = K - A
            return K - A*np.exp(s1*t) - B*np.exp(s2*t)
        else:
            wd = wn*np.sqrt(1-zeta**2)
            phi = np.arccos(zeta)
            return K*(1 - (1/np.sqrt(1-zeta**2)) * np.exp(-zeta*wn*t) * np.sin(wd*t+phi))

    # initial guess
    K_guess = data["hr_after_ftp"] - data["hr_after_zone2"]
    p0 = [K_guess, 0.05, 0.7]
    params, _ = curve_fit(pt2, t, hr_step, p0=p0, bounds=(0, np.inf))
    K_fit, wn, zeta = params

    # 3) tangent method to find L and T
    # generate smooth fit curve
    t_fit = np.linspace(t[0], t[-1], 1000)
    hr_fit = pt2(t_fit, *params) + hr0

    # derivative
    dhr = np.gradient(hr_fit, t_fit)
    idx_inflect = np.argmax(dhr)
    t_i = t_fit[idx_inflect]
    hr_i = hr_fit[idx_inflect]
    slope = dhr[idx_inflect]

    # tangent line: y = hr_i + slope*(t - t_i)
    # L = intercept where tangent = hr0
    L = t_i - (hr_i - hr0)/slope

    # 63% of final step: y63 = hr0 + 0.63*K_fit
    y63 = hr0 + 0.63*K_fit
    # solve for T: t when tangent = y63 → y63 = hr_i + slope*(T - t_i)
    T = t_i + (y63 - hr_i)/slope - L

    # 4) normalize gain by ΔPower
    Δu = data["zone4_power"] - data["zone2_power"]
    process_gain = K_fit / Δu

    # CHR formulas
    # 0% overshoot
    Kp_0  = 0.3 * T / (process_gain * L)
    Ti_0  = T
    Td_0  = 0.5 * L
    # 20% overshoot
    Kp_20 = 0.6 * T / (process_gain * L)
    Ti_20 = T
    Td_20 = 0.5 * L

    if plot:
        plt.figure(figsize=(10,6))
        plt.plot(t, hr, 'o', label="HR data")
        plt.plot(t_fit, hr_fit, '-', label="PT2 fit")
        # tangent
        tangent = hr_i + slope*(t_fit - t_i)
        plt.plot(t_fit, tangent, '--', label="Tangent")
        plt.axvline(L, color='C3', linestyle='--', label=f"L ≈ {L:.1f}s")
        plt.axvline(L+T, color='C4', linestyle='--', label=f"L+T ≈ {(L+T):.1f}s")
        plt.axhline(y63, color='gray', linestyle=':', label=f"63% ≈ {y63:.1f} bpm")
        plt.scatter([t_i],[hr_i], color='k', zorder=5, label=f"Inflection @ {t_i:.1f}s")
        plt.title("PT2 Fit + Tangent Method")
        plt.xlabel("Time since step (s)")
        plt.ylabel("Heart Rate (bpm)")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.show()

    return {
        "K_fit": K_fit, "wn": wn, "zeta": zeta,
        "L": L, "T": T,
        "process_gain": process_gain,
        "pid_chr_0":  {"Kp":Kp_0,  "Ti":Ti_0,  "Td":Td_0},
        "pid_chr_20": {"Kp":Kp_20, "Ti":Ti_20, "Td":Td_20}
    }

if __name__=="__main__":
    import json

    with open("sequence_results.json") as f:
        data = json.load(f)

    fit_result = fit_pt2_from_samples(data)
    print(json.dumps(fit_result, indent=2))
