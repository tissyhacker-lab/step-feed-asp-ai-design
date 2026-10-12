from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path

import numpy as np

import model_step_feed as mech


OUT = Path(__file__).resolve().parent / "output"


def make_dataset(n: int, start: int) -> tuple[np.ndarray, np.ndarray]:
    u = mech.halton(n, 7, start=start)
    f = mech.simplex_from_unit(u[:, :4])
    q = 3.5 + u[:, 4] * 4.5
    s0 = 200.0 + u[:, 5] * 160.0
    recycle = 0.30 + u[:, 6] * 0.30
    x = np.column_stack([f[:, :3], q, s0, recycle])
    y = np.empty((n, 6))
    for i in range(n):
        r = mech.simulate(q[i], s0[i], recycle[i], f[i])
        y[i] = [r["se"], *r["o2_zone"], r["o2_total"]]
    return x, y


def powers(n_features: int, degree: int) -> list[tuple[int, ...]]:
    result = [(0,) * n_features]
    for total_degree in range(1, degree + 1):
        for comb in itertools.combinations_with_replacement(range(n_features), total_degree):
            p = [0] * n_features
            for idx in comb:
                p[idx] += 1
            result.append(tuple(p))
    return result


def poly_matrix(z: np.ndarray, pp: list[tuple[int, ...]]) -> np.ndarray:
    cols = []
    for p in pp:
        col = np.ones(len(z))
        for j, exponent in enumerate(p):
            if exponent:
                col *= z[:, j] ** exponent
        cols.append(col)
    return np.column_stack(cols)


def fit_poly(x: np.ndarray, y: np.ndarray, degree: int, alpha: float = 1e-6) -> dict:
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    pp = powers(x.shape[1], degree)
    phi = poly_matrix((x - mean) / scale, pp)
    reg = np.eye(phi.shape[1]) * alpha
    reg[0, 0] = 0.0
    coef = np.linalg.solve(phi.T @ phi + reg, phi.T @ y)
    return {"kind": "poly", "degree": degree, "mean": mean, "scale": scale, "powers": pp, "coef": coef}


def predict_poly(model: dict, x: np.ndarray) -> np.ndarray:
    z = (x - model["mean"]) / model["scale"]
    return poly_matrix(z, model["powers"]) @ model["coef"]


def predict_knn(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray, k: int = 12) -> np.ndarray:
    mean, scale = x_train.mean(axis=0), x_train.std(axis=0)
    scale[scale == 0] = 1.0
    a, b = (x_train - mean) / scale, (x_test - mean) / scale
    out = np.empty((len(b), y_train.shape[1]))
    for start in range(0, len(b), 128):
        chunk = b[start : start + 128]
        d2 = ((chunk[:, None, :] - a[None, :, :]) ** 2).sum(axis=2)
        idx = np.argpartition(d2, k, axis=1)[:, :k]
        near = np.take_along_axis(d2, idx, axis=1)
        w = 1.0 / np.maximum(near, 1e-12)
        vals = y_train[idx]
        out[start : start + len(chunk)] = (vals * w[:, :, None]).sum(axis=1) / w.sum(axis=1)[:, None]
    return out


def fit_rff(x: np.ndarray, y: np.ndarray, n_features: int = 320, alpha: float = 1e-4, seed: int = 2026) -> dict:
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    z = (x - mean) / scale
    probe = z[: min(800, len(z))]
    d2 = ((probe[::2, None, :] - probe[1::2][None, :, :]) ** 2).sum(axis=2).ravel()
    med = float(np.median(d2[d2 > 0]))
    gamma = 1.0 / max(med, 1e-6)
    rng = np.random.default_rng(seed)
    w = rng.normal(0.0, math.sqrt(2.0 * gamma), size=(z.shape[1], n_features))
    phase = rng.uniform(0.0, 2.0 * math.pi, size=n_features)
    phi = math.sqrt(2.0 / n_features) * np.cos(z @ w + phase)
    phi = np.column_stack([np.ones(len(phi)), phi])
    reg = np.eye(phi.shape[1]) * alpha
    reg[0, 0] = 0.0
    coef = np.linalg.solve(phi.T @ phi + reg, phi.T @ y)
    return {"mean": mean, "scale": scale, "w": w, "phase": phase, "coef": coef}


def predict_rff(model: dict, x: np.ndarray) -> np.ndarray:
    z = (x - model["mean"]) / model["scale"]
    phi = math.sqrt(2.0 / model["w"].shape[1]) * np.cos(z @ model["w"] + model["phase"])
    phi = np.column_stack([np.ones(len(phi)), phi])
    return phi @ model["coef"]


def score(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    bod_rmse = float(np.sqrt(np.mean((pred[:, 0] - y[:, 0]) ** 2)))
    zone_rmse = float(np.sqrt(np.mean((pred[:, 1:5] - y[:, 1:5]) ** 2)))
    bod_r2 = 1.0 - float(np.sum((pred[:, 0] - y[:, 0]) ** 2) / np.sum((y[:, 0] - y[:, 0].mean()) ** 2))
    zone_r2 = 1.0 - float(np.sum((pred[:, 1:5] - y[:, 1:5]) ** 2) / np.sum((y[:, 1:5] - y[:, 1:5].mean()) ** 2))
    return {"bod_rmse": bod_rmse, "zone_o2_rmse": zone_rmse, "bod_r2": bod_r2, "zone_o2_r2": zone_r2}


def candidate_matrix(n: int = 32768) -> tuple[np.ndarray, np.ndarray]:
    f = mech.sample_splits(n, start=100_003)
    normal = np.all((f >= 0.05) & (f <= 0.60), axis=1)
    f = f[normal]
    x = np.column_stack([
        f[:, :3],
        np.full(len(f), mech.Q_DESIGN),
        np.full(len(f), mech.S0_DESIGN),
        np.full(len(f), mech.R_DESIGN),
    ])
    return f, x


def model_recommendation(model: dict, f: np.ndarray, x: np.ndarray) -> np.ndarray:
    yp = predict_poly(model, x)
    zones = yp[:, 1:5]
    mean_o2 = zones.mean(axis=1)
    peak = zones.max(axis=1) / mean_o2
    cv = zones.std(axis=1) / mean_o2
    obj = 0.50 * yp[:, 0] / mech.S_TARGET + 0.30 * peak + 0.15 * cv + 0.05 * yp[:, 5] / mech.O2_SUPPLIED
    ok = (yp[:, 0] <= mech.S_TARGET) & (yp[:, 5] <= mech.O2_SUPPLIED)
    order = np.argsort(np.where(ok, obj, np.inf))
    for idx in order[:300]:
        if not ok[idx]:
            continue
        r = mech.simulate(mech.Q_DESIGN, mech.S0_DESIGN, mech.R_DESIGN, f[idx])
        if mech.engineering_feasible(mech.Q_DESIGN, mech.S0_DESIGN, f[idx], r):
            return f[idx]
    return np.full(4, np.nan)


def split_descriptors(f: np.ndarray) -> tuple[float, float]:
    """Return feed centre (early=1, late=4) and relative split imbalance."""
    centre = float(np.dot(np.arange(1, 5), f))
    imbalance = float(np.std(f) / 0.25)
    return centre, imbalance


def refine_for_capacity(seed: np.ndarray, capacity: float) -> tuple[np.ndarray, dict] | None:
    """Deterministic pairwise-transfer search on the feed simplex."""
    f = np.array(seed, dtype=float)
    r = mech.simulate(mech.Q_DESIGN, mech.S0_DESIGN, mech.R_DESIGN, f)

    def acceptable(candidate: np.ndarray, result: dict) -> bool:
        return bool(
            np.all(candidate >= 0.05 - 1e-10)
            and np.all(candidate <= 0.60 + 1e-10)
            and result["o2_total"] <= mech.O2_SUPPLIED + 1e-8
            and np.max(result["o2_zone"]) <= capacity + 1e-8
        )

    if not acceptable(f, r):
        return None
    for step in [0.02, 0.01, 0.005, 0.002, 0.001, 0.0005, 0.0002, 0.0001]:
        improved = True
        while improved:
            improved = False
            best_f, best_r = f, r
            for receiver in range(4):
                for donor in range(4):
                    if receiver == donor:
                        continue
                    trial = f.copy()
                    trial[receiver] += step
                    trial[donor] -= step
                    if np.any(trial < 0.05 - 1e-10) or np.any(trial > 0.60 + 1e-10):
                        continue
                    trial_r = mech.simulate(mech.Q_DESIGN, mech.S0_DESIGN, mech.R_DESIGN, trial)
                    if acceptable(trial, trial_r) and trial_r["se"] < best_r["se"] - 1e-10:
                        best_f, best_r = trial, trial_r
            if best_r["se"] < r["se"] - 1e-10:
                f, r, improved = best_f, best_r, True
    return f, r


def calculate_capacity_frontier() -> tuple[np.ndarray, list[dict]]:
    """Mechanistically verify the best feed split over a sweep of local capacities."""
    splits = mech.sample_splits(131072, start=300_003)
    records = []
    for f in splits:
        if not np.all((f >= 0.05) & (f <= 0.60)):
            continue
        r = mech.simulate(mech.Q_DESIGN, mech.S0_DESIGN, mech.R_DESIGN, f)
        if r["o2_total"] <= mech.O2_SUPPLIED and r["se"] <= mech.S_TARGET:
            centre, imbalance = split_descriptors(f)
            records.append((f, r, centre, imbalance))

    capacities = np.concatenate([
        np.linspace(3850.0, 4400.0, 23),
        np.linspace(4450.0, 5600.0, 24),
    ])
    frontier = []
    previous = np.full(4, 0.25)
    for capacity in capacities:
        feasible = [item for item in records if np.max(item[1]["o2_zone"]) <= capacity]
        seeds = [previous, np.full(4, 0.25)]
        seeds.extend(item[0] for item in sorted(feasible, key=lambda item: item[1]["se"])[:8])
        refined = [refine_for_capacity(seed, capacity) for seed in seeds]
        refined = [item for item in refined if item is not None]
        if not refined:
            continue
        best_se = min(item[1]["se"] for item in refined)
        near_optimal = [item for item in refined if item[1]["se"] <= best_se + 5e-5]
        f_best, r_best = min(near_optimal, key=lambda item: np.linalg.norm(item[0] - previous))
        previous = f_best
        centre, imbalance = split_descriptors(f_best)
        frontier.append({
            "capacity_lb_d": float(capacity),
            "se_mg_L": float(r_best["se"]),
            "max_zone_o2_lb_d": float(np.max(r_best["o2_zone"])),
            "total_o2_lb_d": float(r_best["o2_total"]),
            **{f"o2_zone_{i+1}_lb_d": float(r_best["o2_zone"][i]) for i in range(4)},
            "feed_centre": centre,
            "split_cv": imbalance,
            **{f"f{i+1}": float(f_best[i]) for i in range(4)},
        })
    scatter = np.array([
        [float(np.max(r["o2_zone"])), float(r["se"]), centre, imbalance, int(np.argmax(r["o2_zone"])) + 1]
        for _, r, centre, imbalance in records
    ])
    return scatter, frontier


def make_tradeoff_svg(path: Path) -> None:
    rows = []
    with (OUT / "candidate_designs.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            f = np.array([float(r[f"f{i}"]) for i in range(1, 5)])
            if np.all((f >= 0.05) & (f <= 0.60)):
                total = float(r["o2_lb_d"])
                peak = float(r["peak_factor"])
                rows.append((peak * total / 4.0, float(r["se_mg_L"]), f))
    xs = np.array([r[0] for r in rows])
    ys = np.array([r[1] for r in rows])
    width, height = 1120, 680
    left, right, top, bottom = 100, 65, 70, 100
    pw, ph = width - left - right, height - top - bottom
    xmin, xmax = 3700.0, min(7600.0, float(np.percentile(xs, 99.2)))
    ymin, ymax = 4.0, 15.5

    def sx(v): return left + (v - xmin) / (xmax - xmin) * pw
    def sy(v): return top + (ymax - v) / (ymax - ymin) * ph

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="52" y="38" font-family="Arial" font-size="25" font-weight="700">The design trade-off: lower BOD requires more local aeration capacity</text>',
    ]
    cap = sx(3900)
    parts.append(f'<rect x="{left}" y="{top}" width="{cap-left:.1f}" height="{ph}" fill="#dcfce7" fill-opacity="0.65"/>')
    for i in range(6):
        xv = xmin + i * (xmax - xmin) / 5
        xp = sx(xv)
        parts += [f'<line x1="{xp:.1f}" y1="{top}" x2="{xp:.1f}" y2="{top+ph}" stroke="#e2e8f0"/>', f'<text x="{xp:.1f}" y="{top+ph+30}" text-anchor="middle" font-family="Arial" font-size="15">{xv:,.0f}</text>']
    for i in range(6):
        yv = ymin + i * (ymax - ymin) / 5
        yp = sy(yv)
        parts += [f'<line x1="{left}" y1="{yp:.1f}" x2="{left+pw}" y2="{yp:.1f}" stroke="#e2e8f0"/>', f'<text x="{left-12}" y="{yp+5:.1f}" text-anchor="end" font-family="Arial" font-size="15">{yv:.1f}</text>']
    for xval, yval, _ in rows:
        if xmin <= xval <= xmax and ymin <= yval <= ymax:
            fill = "#93c5fd" if xval <= 3900 else "#cbd5e1"
            parts.append(f'<circle cx="{sx(xval):.1f}" cy="{sy(yval):.1f}" r="2.7" fill="{fill}" fill-opacity="0.60"/>')
    parts += [
        f'<line x1="{cap:.1f}" y1="{top}" x2="{cap:.1f}" y2="{top+ph}" stroke="#dc2626" stroke-width="3" stroke-dasharray="9 7"/>',
        f'<text x="{cap+10:.1f}" y="{top+22}" font-family="Arial" font-size="15" fill="#b91c1c">3,900 lb O₂/d zone limit</text>',
    ]
    summary = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    marks = [
        ("AI round 1", summary["nominal_optimum"], "#dc2626", 14, -12),
        ("Constrained AI", summary["audited_optimum"], "#0f766e", 14, -12),
        ("EPA split", summary["equal_split_reveal"], "#7c3aed", 14, 24),
    ]
    for label, item, color, dx, dy in marks:
        xval = max(item["o2_zones"]) if "o2_zones" in item else max(item["o2_zone"])
        yval = item["se"]
        parts.append(f'<circle cx="{sx(xval):.1f}" cy="{sy(yval):.1f}" r="8" fill="{color}" stroke="white" stroke-width="3"/>')
        parts.append(f'<text x="{sx(xval)+dx:.1f}" y="{sy(yval)+dy:.1f}" font-family="Arial" font-size="16" font-weight="700" fill="{color}">{label}</text>')
    parts += [
        f'<text x="{left+pw/2}" y="{height-32}" text-anchor="middle" font-family="Arial" font-size="19">Maximum zone oxygen demand (lb O₂/d)</text>',
        f'<text x="26" y="{top+ph/2}" transform="rotate(-90 26 {top+ph/2})" text-anchor="middle" font-family="Arial" font-size="19">Effluent BOD₅ (mg/L)</text>',
        '</svg>',
    ]
    path.write_text("\n".join(parts), encoding="utf-8")


def make_capacity_value_svg(scatter: np.ndarray, frontier: list[dict], path: Path) -> None:
    width, height = 1120, 1180
    top, ph = 100, 446
    left_a, pw_a = 60, 1000
    b_top, b_ph = 720, 350
    left_b, pw_b = 80, 658
    feed_colors = ["#2563eb", "#16a34a", "#f97316", "#7c3aed"]
    def sx_a(v): return left_a + (v - 3700.0) / (7550.0 - 3700.0) * pw_a
    def sy_a(v): return top + (15.5 - v) / (15.5 - 4.0) * ph
    def sx_b(v): return left_b + (v - 3825.0) / (4550.0 - 3825.0) * pw_b
    def sy_b(v): return b_top + (11.3 - v) / (11.3 - 6.2) * b_ph
    c_left, c_top, c_w, c_h = 820, 720, 238, 350
    def sx_c(v): return c_left + (v - 3850.0) / (4500.0 - 3850.0) * c_w
    def sy_o2(v): return c_top + (16000.0 - v) / 16000.0 * c_h
    def annual_energy_cost(o2_lb_d):
        return o2_lb_d * 0.453592 * 365.0 * 0.10 / 1.7
    def sy_cost(v): return c_top + (152200.0 - v) / (152200.0 - 149500.0) * c_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="42" y="38" font-family="Arial" font-size="25" font-weight="700">Design space and the value of local aeration capacity</text>',
        '<text x="60" y="78" font-family="Arial" font-size="18" font-weight="700">A  All screened designs</text>',
        '<text x="80" y="698" font-family="Arial" font-size="18" font-weight="700">B  Capacity frontier</text>',
    ]
    for xv in np.linspace(3700, 7550, 5):
        xp = sx_a(xv); parts += [f'<line x1="{xp:.1f}" y1="{top}" x2="{xp:.1f}" y2="{top+ph}" stroke="#e2e8f0"/>', f'<text x="{xp:.1f}" y="{top+ph+24}" text-anchor="middle" font-family="Arial" font-size="12">{xv:,.0f}</text>']
    for yv in np.linspace(4, 15.5, 5):
        yp = sy_a(yv); parts += [f'<line x1="{left_a}" y1="{yp:.1f}" x2="{left_a+pw_a}" y2="{yp:.1f}" stroke="#e2e8f0"/>', f'<text x="{left_a-9}" y="{yp+4:.1f}" text-anchor="end" font-family="Arial" font-size="12">{yv:.1f}</text>']
    for xv in [3900, 4100, 4200, 4400, 4500]:
        xp = sx_b(xv); parts += [f'<line x1="{xp:.1f}" y1="{b_top}" x2="{xp:.1f}" y2="{b_top+b_ph}" stroke="#e2e8f0"/>', f'<text x="{xp:.1f}" y="{b_top+b_ph+24}" text-anchor="middle" font-family="Arial" font-size="11">{xv:,.0f}</text>']
    for yv in [6.5, 7.5, 8.5, 9.5, 10.5, 11.0]:
        yp = sy_b(yv); parts += [f'<line x1="{left_b}" y1="{yp:.1f}" x2="{left_b+pw_b}" y2="{yp:.1f}" stroke="#e2e8f0"/>', f'<text x="{left_b-8}" y="{yp+4:.1f}" text-anchor="end" font-family="Arial" font-size="11">{yv:.1f}</text>']
    stride = max(1, len(scatter) // 2500)
    for xval, yval, _centre, _imbalance, bottleneck in scatter[::stride]:
        if int(bottleneck) == 4:
            fill, opacity = "#dc2626", 0.22
        else:
            fill, opacity = "#94a3b8", 0.22
        parts.append(f'<circle cx="{sx_a(xval):.1f}" cy="{sy_a(yval):.1f}" r="2.5" fill="{fill}" fill-opacity="{opacity}"/>')
    coords_a = " ".join(f'{sx_a(r["max_zone_o2_lb_d"]):.1f},{sy_a(r["se_mg_L"]):.1f}' for r in frontier)
    coords_b = " ".join(f'{sx_b(r["capacity_lb_d"]):.1f},{sy_b(r["se_mg_L"]):.1f}' for r in frontier if r["capacity_lb_d"] <= 4550)
    parts += [
        f'<polyline points="{coords_a}" fill="none" stroke="#17324d" stroke-width="4" stroke-linejoin="round"/>',
        f'<polyline points="{coords_b}" fill="none" stroke="#17324d" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>',
        f'<text x="{sx_a(4490):.1f}" y="{sy_a(12.0):.1f}" font-family="Arial" font-size="15" font-weight="700" fill="#991b1b">Red band only: Zone 4 controls</text>',
        f'<text x="{sx_a(4490):.1f}" y="{sy_a(11.55):.1f}" font-family="Arial" font-size="14" fill="#991b1b">O₄ = 281.0Sₑ + 758.6</text>',
        f'<line x1="{sx_a(5050):.1f}" y1="{sy_a(13.0):.1f}" x2="{sx_a(4850):.1f}" y2="{sy_a(14.55):.1f}" stroke="#991b1b" stroke-width="1.5"/>',
        f'<rect x="{sx_b(4400):.1f}" y="{b_top}" width="{sx_b(4550)-sx_b(4400):.1f}" height="{b_ph}" fill="#f1f5f9" fill-opacity="0.65"/>',
    ]
    # Redraw the plateau over the shaded total-capacity-limited region.
    parts.append(f'<polyline points="{coords_b}" fill="none" stroke="#17324d" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>')
    selected = {3850, 3900, 4100, 4200, 4400}
    for row in frontier:
        if int(round(row["capacity_lb_d"])) in selected:
            parts.append(f'<circle cx="{sx_b(row["capacity_lb_d"]):.1f}" cy="{sy_b(row["se_mg_L"]):.1f}" r="6" fill="#0f766e" stroke="white" stroke-width="2"/>')
            parts.append(f'<text x="{sx_b(row["capacity_lb_d"])+7:.1f}" y="{sy_b(row["se_mg_L"])-7:.1f}" font-family="Arial" font-size="11" fill="#0f766e">C={row["capacity_lb_d"]:,.0f}</text>')
    parts += [
        f'<text x="{sx_b(4510):.1f}" y="{sy_b(7.05):.1f}" text-anchor="end" font-family="Arial" font-size="12" font-weight="700" fill="#475569">Total O₂ limit binds</text>',
        f'<text x="{left_a+pw_a/2}" y="{top+ph+52}" text-anchor="middle" font-family="Arial" font-size="14">Maximum zone O₂ demand (lb/d)</text>',
        f'<text x="{left_b+pw_b/2}" y="{b_top+b_ph+52}" text-anchor="middle" font-family="Arial" font-size="14">Assumed available local capacity C (lb/d)</text>',
        f'<text x="22" y="{top+ph/2}" transform="rotate(-90 22 {top+ph/2})" text-anchor="middle" font-family="Arial" font-size="14">Predicted effluent BOD₅ (mg/L)</text>',
        '<circle cx="85" cy="636" r="6" fill="#94a3b8" fill-opacity="0.45"/><text x="99" y="641" font-family="Arial" font-size="15" fill="#334155">all candidates</text>',
        '<circle cx="235" cy="636" r="6" fill="#dc2626" fill-opacity="0.55"/><text x="249" y="641" font-family="Arial" font-size="15" fill="#334155">Zone 4 controls (diagnostic only)</text>',
    ]
    summary = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    first = summary["nominal_optimum"]
    reveal = summary["equal_split_reveal"]
    markers = [
        ("EPA split", max(reveal["o2_zones"]), reveal["se"], "#7c3aed", 10, 18),
        ("AI round 1", max(first["o2_zones"]), first["se"], "#dc2626", 10, -10),
    ]
    for label, xval, yval, color, dx, dy in markers:
        parts.append(f'<circle cx="{sx_a(xval):.1f}" cy="{sy_a(yval):.1f}" r="7" fill="{color}" stroke="white" stroke-width="2"/>')
        parts.append(f'<text x="{sx_a(xval)+dx:.1f}" y="{sy_a(yval)+dy:.1f}" font-family="Arial" font-size="13" font-weight="700" fill="{color}">{label}</text>')
    # Touching stacked columns show continuous zone oxygen allocation; the cost
    # line uses the right axis and includes energy only.
    parts.append('<text x="939" y="698" text-anchor="middle" font-family="Arial" font-size="17" font-weight="700" fill="#17324d">C  Zone O₂ and cost</text>')
    for cap in [3850, 4150, 4500]:
        x = sx_c(cap)
        parts.append(f'<line x1="{x:.1f}" y1="{c_top}" x2="{x:.1f}" y2="{c_top+c_h}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{x:.1f}" y="{c_top+c_h+20}" text-anchor="middle" font-family="Arial" font-size="12">{cap:,}</text>')
    for oxygen in [0, 4000, 8000, 12000, 16000]:
        y = sy_o2(oxygen)
        parts.append(f'<line x1="{c_left}" y1="{y:.1f}" x2="{c_left+c_w}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{c_left-8}" y="{y+4:.1f}" text-anchor="end" font-family="Arial" font-size="12">{oxygen/1000:.0f}k</text>')
    parts.append(f'<rect x="{sx_c(4400):.1f}" y="{c_top}" width="{sx_c(4500)-sx_c(4400):.1f}" height="{c_h}" fill="#f1f5f9" fill-opacity="0.85"/>')
    plotted = [r for r in frontier if r["capacity_lb_d"] <= 4500.0]
    caps = [r["capacity_lb_d"] for r in plotted]
    edges = [3850.0]
    edges.extend((caps[i-1] + caps[i]) / 2.0 for i in range(1, len(caps)))
    edges.append(4500.0)
    for j, row in enumerate(plotted):
        x0, x1 = sx_c(edges[j]), sx_c(edges[j+1])
        cumulative = 0.0
        for i, color in enumerate(feed_colors):
            next_cumulative = cumulative + row[f"o2_zone_{i+1}_lb_d"]
            y_top, y_bottom = sy_o2(next_cumulative), sy_o2(cumulative)
            parts.append(f'<rect x="{x0:.1f}" y="{y_top:.1f}" width="{x1-x0+0.5:.1f}" height="{y_bottom-y_top:.1f}" fill="{color}" stroke="white" stroke-opacity="0.28" stroke-width="0.5"/>')
            cumulative = next_cumulative
    cost_coords = " ".join(f'{sx_c(r["capacity_lb_d"]):.1f},{sy_cost(annual_energy_cost(r["total_o2_lb_d"])):.1f}' for r in frontier if r["capacity_lb_d"] <= 4500.0)
    parts.append(f'<polyline points="{cost_coords}" fill="none" stroke="#be123c" stroke-width="3" stroke-dasharray="7 4"/>')
    for value in [150000, 151000, 152000]:
        y = sy_cost(value)
        parts.append(f'<text x="{c_left+c_w+8}" y="{y+4:.1f}" font-family="Arial" font-size="12" fill="#be123c">${value/1000:.0f}k/y</text>')
    for i, color in enumerate(feed_colors):
        x = 825 + i * 50
        parts.append(f'<rect x="{x}" y="1115" width="12" height="12" fill="{color}"/><text x="{x+15}" y="1126" font-family="Arial" font-size="12">O{i+1}</text>')
    parts.append('<line x1="830" y1="1147" x2="854" y2="1147" stroke="#be123c" stroke-width="4" stroke-dasharray="7 4"/><text x="861" y="1152" font-family="Arial" font-size="11" fill="#be123c">cost at 1.7 kg O₂/kWh</text>')
    parts.append(f'<text x="{sx_c(4480):.1f}" y="{c_top+45}" text-anchor="end" font-family="Arial" font-size="10" font-weight="700" fill="#475569">plateau</text>')
    parts.append(f'<text x="{c_left+c_w/2}" y="1175" text-anchor="middle" font-family="Arial" font-size="11">C = one-zone limit; energy only; $0.10/kWh</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    x_test, y_test = make_dataset(2048, start=900_003)
    sizes = [512, 1024, 2048, 4096, 8192]
    repeats = 5
    learning = []
    f_cand, x_cand = candidate_matrix()
    recommendations: dict[tuple[int, int], np.ndarray] = {}
    for rep in range(repeats):
        x_all, y_all = make_dataset(8192, start=20_003 + rep * 50_000)
        for n in sizes:
            model = fit_poly(x_all[:n], y_all[:n], degree=3)
            m = score(y_test, predict_poly(model, x_test))
            rec = model_recommendation(model, f_cand, x_cand)
            recommendations[(rep, n)] = rec
            learning.append({"repeat": rep + 1, "n": n, **m, **{f"f{i+1}": rec[i] for i in range(4)}})

    learning_summary = []
    for n in sizes:
        subset = [r for r in learning if r["n"] == n]
        row = {"n": n}
        for key in ["bod_rmse", "zone_o2_rmse", "bod_r2", "zone_o2_r2"]:
            vals = np.array([r[key] for r in subset])
            row[f"{key}_mean"] = float(vals.mean())
            row[f"{key}_sd"] = float(vals.std(ddof=1))
        ref = np.array([recommendations[(rep, 8192)] for rep in range(repeats)])
        cur = np.array([recommendations[(rep, n)] for rep in range(repeats)])
        row["split_l1_pp_mean"] = float(np.nanmean(np.abs(cur - ref).sum(axis=1) * 100.0))
        row["max_fraction_sd_pp"] = float(np.nanmax(np.nanstd(cur * 100.0, axis=0, ddof=1)))
        learning_summary.append(row)

    x_train, y_train = make_dataset(4096, start=20_003)
    models = []
    for degree in [2, 3]:
        model = fit_poly(x_train, y_train, degree=degree)
        models.append((f"Polynomial ridge degree {degree}", score(y_test, predict_poly(model, x_test))))
    models.append(("Distance-weighted kNN k=12", score(y_test, predict_knn(x_train, y_train, x_test, k=12))))
    rff = fit_rff(x_train, y_train)
    models.append(("RBF random-feature ridge", score(y_test, predict_rff(rff, x_test))))

    with (OUT / "learning_curve_fixed_test.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(learning_summary[0]))
        writer.writeheader(); writer.writerows(learning_summary)
    with (OUT / "model_comparison.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        rows = [{"model": name, **m} for name, m in models]
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    scatter, frontier = calculate_capacity_frontier()
    with (OUT / "capacity_frontier.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(frontier[0]))
        writer.writeheader(); writer.writerows(frontier)
    result = {
        "fixed_test_n": len(x_test),
        "repeats": repeats,
        "learning_curve": learning_summary,
        "models": [{"model": n, **m} for n, m in models],
        "capacity_frontier": frontier,
    }
    (OUT / "surrogate_benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    make_capacity_value_svg(scatter, frontier, OUT / "capacity_value_curve.svg")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
