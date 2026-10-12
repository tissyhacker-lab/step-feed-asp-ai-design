# Step-feed ASP AI design: reproducibility package

Authors: HU TONGYU (A0332797N) and MA DINGNA (A0319575R)

Repository: https://github.com/tissyhacker-lab/step-feed-asp-ai-design

## Contents

- `model_step_feed.py`: four-zone CSTR model, calibration, sampling, screening and base results.
- `benchmark_surrogates.py`: fixed-test surrogate comparison, convergence analysis, capacity frontier and SVG figure generation.
- `build_report.py`: shared Word table and formatting helpers.
- `build_report_final.py`: final five-page report generator.
- `render_svgs.js`: SVG-to-PNG rendering with Sharp.
- `output/*.csv` and `output/*.json`: candidate designs, learning curve, model comparison, capacity frontier and reported results.
- `output/capacity_value_curve.*`: final report figure in SVG and PNG.
- `report/`: final DOCX and PDF.

## Model definitions needed for reproduction

Each aggregate zone has `V_i = 0.50 MG`. The Zone 1 soluble-BOD balance includes recycled soluble BOD explicitly:

`0 = R Q S_4 + f_1 Q S_0 - Q(R + f_1)S_1 - kappa V_1 S_1`.

For Zones 2-4:

`0 = q_(i-1) S_(i-1) + f_i Q S_0 - q_i S_i - kappa V_i S_i`, with `q_i = Q(R + sum_(j<=i) f_j)`.

The oxygen-distribution metrics are `O_bar = sum(O_i)/4`, `P = max(O_i)/O_bar`, and `CV = sqrt(sum((O_i-O_bar)^2)/4)/O_bar`.

Figure C calculates its single energy-cost curve with oxygen-transfer efficiency `1.7 kg O2/kWh`, electricity price `$0.10/kWh`, and 365 days/year. The `1.2-2.2 kg O2/kWh` values in the report are sensitivity bounds, not the plotted line.

## Reproduction order

1. Install Python dependencies from `requirements.txt` and Node.js package `sharp` if PNG rendering is required.
2. Run `python model_step_feed.py` from the package root.
3. Run `python benchmark_surrogates.py`.
4. Run `node render_svgs.js` to regenerate PNG figures.
5. Run `python build_report_final.py`, then export the DOCX to PDF with Microsoft Word or LibreOffice.

The fixed test contains 2,048 Halton cases beginning at index 900,003. Training sets use five blocks beginning at 20,003 and then increasing by 50,000. Inputs are standardized using each training block's mean and standard deviation. Reported RMSE units are mg/L for soluble BOD and lb O2/d for zone oxygen demand.

## Evidence boundary

The low surrogate RMSE demonstrates agreement with the assumed mechanistic label generator inside the sampled range. It is not field validation. The EPA 11 mg/L value is used for one-point calibration and cannot also serve as independent validation of final effluent compliance.
