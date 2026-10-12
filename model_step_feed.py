from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path

import numpy as np


OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(parents=True, exist_ok=True)

# Blind design basis extracted from the 2021 EPA SABTP feasibility design.
Q_DESIGN = 5.0  # MGD
Q_PEAK = 12.5  # MGD
V_TOTAL = 2.0  # MG, two 1.0-MG reactors in parallel
N_ZONES = 4
V_ZONE = V_TOTAL / N_ZONES
R_DESIGN = 2.1 / 5.0
S0_DESIGN = 11_700.0 / (8.34 * Q_DESIGN)  # mg/L from reported BOD load
S_TARGET = 15.0  # mg/L screening limit
S_REVEAL = 11.0  # mg/L reported modelled CBOD5
MLSS = 3_000.0  # mg/L
O2_REQUIRED = 15_400.0  # lb/d
O2_SUPPLIED = 15_600.0  # lb/d


def halton(n: int, dim: int, start: int = 1) -> np.ndarray:
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
    if dim > len(primes):
        raise ValueError("Increase prime list")

    def radical_inverse(index: int, base: int) -> float:
        value, factor = 0.0, 1.0 / base
        while index:
            index, digit = divmod(index, base)
            value += digit * factor
            factor /= base
        return value

    return np.array(
        [[radical_inverse(i, primes[j]) for j in range(dim)] for i in range(start, start + n)],
        dtype=float,
    )


def simplex_from_unit(u: np.ndarray) -> np.ndarray:
    # Exponential normalization maps independent uniform values to Dirichlet(1),
    # giving uniform coverage of the four-part feed simplex.
    e = -np.log(np.clip(u, 1e-12, 1 - 1e-12))
    return e / e.sum(axis=1, keepdims=True)


def solve_substrate(kappa: float, q: float, s0: float, recycle: float, fractions: np.ndarray) -> np.ndarray:
    """Solve four steady-state CSTR balances including soluble BOD in RAS."""
    cumulative = np.cumsum(fractions)
    flows = q * (recycle + cumulative)
    a = np.zeros((N_ZONES, N_ZONES), dtype=float)
    b = q * fractions * s0
    for i in range(N_ZONES):
        a[i, i] = flows[i] + kappa * V_ZONE
        if i > 0:
            a[i, i - 1] = -flows[i - 1]
    # RAS soluble concentration is approximated as final-effluent concentration.
    a[0, -1] -= recycle * q
    return np.linalg.solve(a, b)


def calibrate_kappa() -> float:
    # Aggregate one-point calibration uses only project influent/effluent data,
    # not the held-out four-zone feed split:
    # Q(S0-Se) = kappa V Se.
    return Q_DESIGN * (S0_DESIGN - S_REVEAL) / (V_TOTAL * S_REVEAL)


KAPPA = calibrate_kappa()


def simulate(q: float, s0: float, recycle: float, fractions: np.ndarray) -> dict[str, float | np.ndarray]:
    s = solve_substrate(KAPPA, q, s0, recycle, fractions)
    removed_zone = KAPPA * V_ZONE * s * 8.34  # lb BOD5/d
    removed_total = float(removed_zone.sum())

    # Carbonaceous oxidation uses the cited 1.1 lb O2/lb peak BOD criterion.
    # The remaining reported plant oxygen requirement is treated as a basin-wide
    # endogenous/other demand and distributed uniformly for screening.
    equal_s = solve_substrate(KAPPA, Q_DESIGN, S0_DESIGN, R_DESIGN, np.full(4, 0.25))
    equal_removed = float((KAPPA * V_ZONE * equal_s * 8.34).sum())
    o2_background = max(0.0, O2_REQUIRED - 1.1 * equal_removed)
    o2_zone = 1.1 * removed_zone + o2_background / N_ZONES
    o2_total = float(o2_zone.sum())
    mean_o2 = float(o2_zone.mean())
    cv_o2 = float(o2_zone.std() / mean_o2)
    peak_factor = float(o2_zone.max() / mean_o2)

    hrt = 24.0 * V_TOTAL / q
    volumetric_loading = q * s0 * 8.34 / (V_TOTAL * 133.681)  # lb/d/1000 ft3
    fm = q * s0 / (V_TOTAL * MLSS)
    return {
        "s": s,
        "se": float(s[-1]),
        "removed_zone": removed_zone,
        "o2_zone": o2_zone,
        "o2_total": o2_total,
        "cv_o2": cv_o2,
        "peak_factor": peak_factor,
        "hrt": hrt,
        "volumetric_loading": volumetric_loading,
        "fm": fm,
    }


def engineering_feasible(
    q: float,
    s0: float,
    fractions: np.ndarray,
    result: dict,
    require_zone_capacity: bool = False,
) -> bool:
    normal_split = bool(np.all(fractions >= 0.05) and np.all(fractions <= 0.60))
    hydraulic = result["hrt"] >= 6.0
    loading = result["volumetric_loading"] <= 50.0
    fm_ok = 0.17 <= result["fm"] <= 0.50
    effluent = result["se"] <= S_TARGET
    oxygen = result["o2_total"] <= O2_SUPPLIED
    zone_oxygen = (not require_zone_capacity) or bool(np.all(result["o2_zone"] <= O2_SUPPLIED / N_ZONES))
    return normal_split and hydraulic and loading and fm_ok and effluent and oxygen and zone_oxygen


def objective(result: dict) -> float:
    # Dimensionless multi-objective screening score. Lower is better.
    # Effluent compliance has the largest weight; oxygen peak and imbalance
    # represent blower/diffuser sizing and operational robustness.
    return (
        0.50 * result["se"] / S_TARGET
        + 0.30 * result["peak_factor"]
        + 0.15 * result["cv_o2"]
        + 0.05 * result["o2_total"] / O2_SUPPLIED
    )


def polynomial_powers(n_features: int, degree: int = 3) -> list[tuple[int, ...]]:
    powers = [(0,) * n_features]
    for total_degree in range(1, degree + 1):
        for comb in itertools.combinations_with_replacement(range(n_features), total_degree):
            p = [0] * n_features
            for idx in comb:
                p[idx] += 1
            powers.append(tuple(p))
    return powers


POWERS = polynomial_powers(6, 3)


def design_matrix(x: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    z = (x - mean) / scale
    cols = []
    for p in POWERS:
        col = np.ones(len(x))
        for j, exponent in enumerate(p):
            if exponent:
                col *= z[:, j] ** exponent
        cols.append(col)
    return np.column_stack(cols)


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float = 1e-6) -> dict:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    phi = design_matrix(x, mean, scale)
    reg = np.eye(phi.shape[1]) * alpha
    reg[0, 0] = 0.0
    coef = np.linalg.solve(phi.T @ phi + reg, phi.T @ y)
    return {"mean": mean, "scale": scale, "coef": coef}


def predict(model: dict, x: np.ndarray) -> np.ndarray:
    return design_matrix(x, model["mean"], model["scale"]) @ model["coef"]


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    err = pred - y
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
        "r2": 1.0 - ss_res / ss_tot,
    }


def generate_training(n: int) -> tuple[np.ndarray, np.ndarray]:
    u = halton(n, 7, start=17)
    f = simplex_from_unit(u[:, :4])
    q = 3.5 + u[:, 4] * (8.0 - 3.5)
    s0 = 200.0 + u[:, 5] * (360.0 - 200.0)
    recycle = 0.30 + u[:, 6] * (0.60 - 0.30)
    x = np.column_stack([f[:, :3], q, s0, recycle])
    y = np.empty((n, 6))
    for i in range(n):
        r = simulate(q[i], s0[i], recycle[i], f[i])
        y[i] = [r["se"], *r["o2_zone"], r["o2_total"]]
    return x, y


def sample_splits(n: int, start: int = 100_003) -> np.ndarray:
    return simplex_from_unit(halton(n, 4, start=start))


def optimize_scenario(
    model: dict,
    q: float,
    s0: float,
    recycle: float,
    n: int = 32768,
    require_zone_capacity: bool = False,
) -> dict:
    f = sample_splits(n)
    normal = np.all((f >= 0.05) & (f <= 0.60), axis=1)
    f = f[normal]
    x = np.column_stack([
        f[:, :3],
        np.full(len(f), q),
        np.full(len(f), s0),
        np.full(len(f), recycle),
    ])
    yp = predict(model, x)
    pred_o2_zone = yp[:, 1:5]
    pred_o2_mean = pred_o2_zone.mean(axis=1)
    pred_peak = pred_o2_zone.max(axis=1) / pred_o2_mean
    pred_cv = pred_o2_zone.std(axis=1) / pred_o2_mean
    # Surrogate objective uses the same normalized priorities. Hard engineering
    # constraints are applied before ranking, then checked again mechanistically.
    j = 0.50 * yp[:, 0] / S_TARGET + 0.30 * pred_peak + 0.15 * pred_cv + 0.05 * yp[:, 5] / O2_SUPPLIED
    global_screen = simulate(q, s0, recycle, np.full(4, 0.25))
    global_ok = (
        global_screen["hrt"] >= 6.0
        and global_screen["volumetric_loading"] <= 50.0
        and 0.17 <= global_screen["fm"] <= 0.50
    )
    predicted_ok = (yp[:, 0] <= S_TARGET) & (yp[:, 5] <= O2_SUPPLIED)
    if require_zone_capacity:
        predicted_ok &= np.all(pred_o2_zone <= O2_SUPPLIED / N_ZONES, axis=1)
    order = np.argsort(np.where(predicted_ok & global_ok, j, np.inf))
    verified = []
    for idx in order[:200]:
        if not np.isfinite(j[idx]) or not global_ok or not predicted_ok[idx]:
            continue
        result = simulate(q, s0, recycle, f[idx])
        if engineering_feasible(q, s0, f[idx], result, require_zone_capacity=require_zone_capacity):
            verified.append((objective(result), f[idx], result, yp[idx]))
    verified.sort(key=lambda item: item[0])
    return {
        "best": verified[0] if verified else None,
        "evaluated": len(f),
        "top_verified": len(verified),
        "global_screen": global_screen,
    }


def make_svg_scatter(rows: list[dict], path: Path) -> None:
    width, height = 1100, 680
    left, right, top, bottom = 100, 60, 65, 105
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = np.array([r["se"] for r in rows])
    ys = np.array([r["peak_factor"] for r in rows])
    colors = np.array([r["f1"] for r in rows])
    xmin, xmax = max(0.0, xs.min() * 0.95), xs.max() * 1.03
    ymin, ymax = ys.min() * 0.98, ys.max() * 1.02

    def sx(x: float) -> float:
        return left + (x - xmin) / (xmax - xmin) * plot_w

    def sy(y: float) -> float:
        return top + (ymax - y) / (ymax - ymin) * plot_h

    def color(v: float) -> str:
        t = min(1.0, max(0.0, (v - 0.05) / 0.55))
        r = int(35 + 215 * t)
        g = int(150 - 70 * t)
        b = int(210 - 150 * t)
        return f"rgb({r},{g},{b})"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="55" y="34" font-family="Arial" font-size="25" font-weight="700">Feasible feed-split designs at the 5 MGD design condition</text>',
    ]
    for i in range(6):
        xval = xmin + i * (xmax - xmin) / 5
        xpix = sx(xval)
        parts.append(f'<line x1="{xpix:.1f}" y1="{top}" x2="{xpix:.1f}" y2="{top+plot_h}" stroke="#d8dee8"/>')
        parts.append(f'<text x="{xpix:.1f}" y="{top+plot_h+32}" text-anchor="middle" font-family="Arial" font-size="16">{xval:.1f}</text>')
    for i in range(6):
        yval = ymin + i * (ymax - ymin) / 5
        ypix = sy(yval)
        parts.append(f'<line x1="{left}" y1="{ypix:.1f}" x2="{left+plot_w}" y2="{ypix:.1f}" stroke="#d8dee8"/>')
        parts.append(f'<text x="{left-14}" y="{ypix+5:.1f}" text-anchor="end" font-family="Arial" font-size="16">{yval:.2f}</text>')
    for r in rows:
        parts.append(f'<circle cx="{sx(r["se"]):.1f}" cy="{sy(r["peak_factor"]):.1f}" r="3.0" fill="{color(r["f1"])}" fill-opacity="0.56"/>')
    parts.extend([
        f'<line x1="{sx(S_TARGET):.1f}" y1="{top}" x2="{sx(S_TARGET):.1f}" y2="{top+plot_h}" stroke="#dc2626" stroke-width="3" stroke-dasharray="9 7"/>',
        f'<text x="{sx(S_TARGET)-8:.1f}" y="{top+22}" text-anchor="end" font-family="Arial" font-size="16" fill="#b91c1c">15 mg/L screen</text>',
        f'<text x="{left+plot_w/2}" y="{height-34}" text-anchor="middle" font-family="Arial" font-size="19">Predicted effluent BOD₅ (mg/L)</text>',
        f'<text x="27" y="{top+plot_h/2}" transform="rotate(-90 27 {top+plot_h/2})" text-anchor="middle" font-family="Arial" font-size="19">Peak zone O₂ demand / mean zone demand</text>',
        '<text x="855" y="650" font-family="Arial" font-size="15" fill="#334155">Point colour: first-stage feed fraction f₁ (blue low, orange high)</text>',
        '</svg>',
    ])
    path.write_text("\n".join(parts), encoding="utf-8")


def make_svg_comparison(summary: dict, path: Path) -> None:
    width, height = 1120, 700
    labels = ["AI round 1", "Illustrative C=3,900", "EPA reveal"]
    colors = ["#2563eb", "#16a34a", "#f97316", "#7c3aed"]
    fractions = [
        summary["nominal_optimum"]["fractions"],
        summary["audited_optimum"]["fractions"],
        summary["equal_split_reveal"]["fractions"],
    ]
    oxy = [
        summary["nominal_optimum"]["o2_zones"],
        summary["audited_optimum"]["o2_zones"],
        summary["equal_split_reveal"]["o2_zones"],
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="48" y="38" font-family="Arial" font-size="25" font-weight="700">Engineering audit changes the AI recommendation</text>',
        '<text x="48" y="78" font-family="Arial" font-size="19" font-weight="700">A. Primary-effluent split by zone</text>',
    ]
    chart_left, chart_top, chart_w, chart_h = 80, 102, 980, 210
    for i in range(6):
        yv = i * 0.1
        yp = chart_top + chart_h - yv / 0.6 * chart_h
        parts.append(f'<line x1="{chart_left}" y1="{yp:.1f}" x2="{chart_left+chart_w}" y2="{yp:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{chart_left-12}" y="{yp+5:.1f}" text-anchor="end" font-family="Arial" font-size="14">{yv*100:.0f}%</text>')
    group_w = chart_w / 3
    bar_w = 48
    for g, vals in enumerate(fractions):
        center = chart_left + group_w * (g + 0.5)
        for z, val in enumerate(vals):
            x = center + (z - 1.5) * (bar_w + 7) - bar_w / 2
            h = val / 0.6 * chart_h
            y = chart_top + chart_h - h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{colors[z]}" rx="2"/>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-6:.1f}" text-anchor="middle" font-family="Arial" font-size="13">{val*100:.1f}</text>')
        parts.append(f'<text x="{center:.1f}" y="{chart_top+chart_h+28}" text-anchor="middle" font-family="Arial" font-size="15" font-weight="700">{labels[g]}</text>')

    parts.append('<text x="48" y="380" font-family="Arial" font-size="19" font-weight="700">B. Zone oxygen demand</text>')
    chart_top2, chart_h2 = 404, 210
    for i in range(6):
        yv = i * 1000
        yp = chart_top2 + chart_h2 - yv / 5000 * chart_h2
        parts.append(f'<line x1="{chart_left}" y1="{yp:.1f}" x2="{chart_left+chart_w}" y2="{yp:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{chart_left-12}" y="{yp+5:.1f}" text-anchor="end" font-family="Arial" font-size="14">{yv:.0f}</text>')
    cap_y = chart_top2 + chart_h2 - (O2_SUPPLIED / 4) / 5000 * chart_h2
    parts.append(f'<line x1="{chart_left}" y1="{cap_y:.1f}" x2="{chart_left+chart_w}" y2="{cap_y:.1f}" stroke="#dc2626" stroke-width="3" stroke-dasharray="9 7"/>')
    parts.append(f'<text x="{chart_left+chart_w-4}" y="{cap_y-7:.1f}" text-anchor="end" font-family="Arial" font-size="14" fill="#b91c1c">screening capacity 3,900 lb O₂/d per zone</text>')
    for g, vals in enumerate(oxy):
        center = chart_left + group_w * (g + 0.5)
        for z, val in enumerate(vals):
            x = center + (z - 1.5) * (bar_w + 7) - bar_w / 2
            h = val / 5000 * chart_h2
            y = chart_top2 + chart_h2 - h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{colors[z]}" rx="2"/>')
        parts.append(f'<text x="{center:.1f}" y="{chart_top2+chart_h2+28}" text-anchor="middle" font-family="Arial" font-size="15" font-weight="700">{labels[g]}</text>')
    for z, color in enumerate(colors):
        x = 270 + z * 145
        parts.append(f'<rect x="{x}" y="660" width="18" height="18" fill="{color}"/>')
        parts.append(f'<text x="{x+25}" y="675" font-family="Arial" font-size="15">Zone {z+1}</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def make_svg_workflow(path: Path) -> None:
    width, height = 1120, 250
    boxes = [
        ("1  Hold out EPA split", "Use real Q, load, volume and capacity"),
        ("2  Generate labels", "4,096 mechanistic simulations"),
        ("3  Train surrogate", "Cubic ridge response surface"),
        ("4  Review and reveal", "Capacity sensitivity then EPA comparison"),
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for i, (title, sub) in enumerate(boxes):
        x = 22 + i * 276
        parts.append(f'<rect x="{x}" y="48" width="238" height="128" fill="#f8fafc" stroke="#94a3b8" stroke-width="2" rx="6"/>')
        parts.append(f'<text x="{x+18}" y="84" font-family="Arial" font-size="19" font-weight="700" fill="#0f172a">{title}</text>')
        parts.append(f'<text x="{x+18}" y="116" font-family="Arial" font-size="15" fill="#334155">{sub.split(" ", 4)[0]} {sub.split(" ", 4)[1]} {sub.split(" ", 4)[2]}</text>')
        parts.append(f'<text x="{x+18}" y="141" font-family="Arial" font-size="15" fill="#334155">{" ".join(sub.split(" ", 4)[3:])}</text>')
        if i < 3:
            parts.append(f'<line x1="{x+238}" y1="112" x2="{x+270}" y2="112" stroke="#0f766e" stroke-width="4"/>')
            parts.append(f'<polygon points="{x+270},112 {x+258},104 {x+258},120" fill="#0f766e"/>')
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    convergence = []
    final_model = None
    x_all, y_all = generate_training(8192)
    test_mask = np.arange(len(x_all)) % 5 == 0
    for n in [512, 1024, 2048, 4096, 8192]:
        train_idx = np.arange(n)[np.arange(n) % 5 != 0]
        test_idx = np.arange(n)[np.arange(n) % 5 == 0]
        model = fit_ridge(x_all[train_idx], y_all[train_idx])
        pred = predict(model, x_all[test_idx])
        row = {"n": n}
        for j, name in enumerate(["se", "o2_zone1", "o2_zone2", "o2_zone3", "o2_zone4", "o2_total"]):
            for k, v in metrics(y_all[test_idx, j], pred[:, j]).items():
                row[f"{name}_{k}"] = v
        convergence.append(row)
        if n == 4096:
            final_model = model

    assert final_model is not None
    equal = np.full(4, 0.25)
    actual = simulate(Q_DESIGN, S0_DESIGN, R_DESIGN, equal)
    nominal_opt = optimize_scenario(final_model, Q_DESIGN, S0_DESIGN, R_DESIGN)
    stress_opt = optimize_scenario(final_model, 7.5, 320.0, R_DESIGN)

    # Distribution chart uses the actual mechanistic outputs of normal-mode splits.
    chart_splits = sample_splits(5000, start=200_003)
    chart_rows = []
    for f in chart_splits:
        if np.all((f >= 0.05) & (f <= 0.60)):
            r = simulate(Q_DESIGN, S0_DESIGN, R_DESIGN, f)
            if engineering_feasible(Q_DESIGN, S0_DESIGN, f, r):
                chart_rows.append({"f1": float(f[0]), "se": r["se"], "peak_factor": r["peak_factor"]})
    make_svg_scatter(chart_rows, OUT / "design_distribution.svg")

    with (OUT / "surrogate_convergence.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(convergence[0]))
        writer.writeheader()
        writer.writerows(convergence)

    with (OUT / "candidate_designs.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        fields = ["f1", "f2", "f3", "f4", "se_mg_L", "peak_factor", "o2_lb_d", "objective", "feasible"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for f in chart_splits:
            r = simulate(Q_DESIGN, S0_DESIGN, R_DESIGN, f)
            writer.writerow({
                "f1": f[0], "f2": f[1], "f3": f[2], "f4": f[3],
                "se_mg_L": r["se"], "peak_factor": r["peak_factor"],
                "o2_lb_d": r["o2_total"], "objective": objective(r),
                "feasible": engineering_feasible(Q_DESIGN, S0_DESIGN, f, r),
            })

    def pack_opt(opt: dict) -> dict:
        if opt["best"] is None:
            r = opt["global_screen"]
            v_hydraulic = Q_DESIGN * 0.0 + 7.5 * 6.0 / 24.0
            v_loading = 7.5 * 320.0 * 8.34 / (50.0 * 133.681)
            return {
                "feasible": False,
                "reason": "No feed split can repair basin-wide hydraulic, organic-loading, and oxygen-capacity violations.",
                "equal_split_screen": {
                    "se": r["se"], "o2_total": r["o2_total"], "hrt": r["hrt"],
                    "loading": r["volumetric_loading"], "fm": r["fm"],
                },
                "minimum_volume_from_6h_HRT_MG": v_hydraulic,
                "minimum_volume_from_50lb_loading_MG": v_loading,
                "additional_oxygen_capacity_lb_d": max(0.0, r["o2_total"] - O2_SUPPLIED),
                "candidates_evaluated": opt["evaluated"],
            }
        score, f, r, pred = opt["best"]
        return {
            "feasible": True,
            "fractions": [float(v) for v in f],
            "objective": float(score),
            "se": r["se"],
            "s_zones": [float(v) for v in r["s"]],
            "o2_zones": [float(v) for v in r["o2_zone"]],
            "o2_total": r["o2_total"],
            "peak_factor": r["peak_factor"],
            "hrt": r["hrt"],
            "loading": r["volumetric_loading"],
            "fm": r["fm"],
            "surrogate_prediction": {
                "se": float(pred[0]),
                "o2_zones": [float(v) for v in pred[1:5]],
                "o2_total": float(pred[5]),
            },
            "candidates_evaluated": opt["evaluated"],
            "top_verified": opt["top_verified"],
        }

    summary = {
        "basis": {
            "Q_design_MGD": Q_DESIGN,
            "Q_peak_MGD": Q_PEAK,
            "V_total_MG": V_TOTAL,
            "S0_design_mg_L": S0_DESIGN,
            "R": R_DESIGN,
            "MLSS_mg_L": MLSS,
            "kappa_per_d_calibrated": KAPPA,
        },
        "equal_split_reveal": {
            "fractions": equal.tolist(),
            "se": actual["se"],
            "s_zones": actual["s"].tolist(),
            "o2_zones": actual["o2_zone"].tolist(),
            "o2_total": actual["o2_total"],
            "peak_factor": actual["peak_factor"],
            "hrt": actual["hrt"],
            "loading": actual["volumetric_loading"],
            "fm": actual["fm"],
            "objective": objective(actual),
        },
        "nominal_optimum": pack_opt(nominal_opt),
        "stress_optimum": pack_opt(stress_opt),
        "convergence": convergence,
        "chart_feasible_count": len(chart_rows),
    }
    (OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    make_svg_workflow(OUT / "workflow.svg")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
