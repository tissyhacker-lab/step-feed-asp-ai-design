from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
RESULTS = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
BENCH = json.loads((OUT / "surrogate_benchmark.json").read_text(encoding="utf-8"))
FRONTIER = BENCH["capacity_frontier"]
DOCX = ROOT / "Step_Feed_AI_Design_Final_v2.docx"

NAVY = "17324D"
TEAL = "0F766E"
BLUE = "2563EB"
PALE = "EAF2F8"
GRID = "D9E2EC"
ORANGE = "F97316"
RED = "B91C1C"
GRAY = "475569"


def shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=90, start=110, bottom=90, end=110) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float], font_size=8.4):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.style = "Table Grid"
    for j, text in enumerate(headers):
        cell = table.rows[0].cells[j]
        cell.width = Cm(widths[j])
        shade(cell, NAVY)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_margins(cell)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = True
        r.font.color.rgb = RGBColor(255, 255, 255)
        r.font.size = Pt(font_size)
    set_repeat_table_header(table.rows[0])
    for i, row_data in enumerate(rows):
        row = table.add_row()
        for j, text in enumerate(row_data):
            cell = row.cells[j]
            cell.width = Cm(widths[j])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            if i % 2:
                shade(cell, "F4F7FA")
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if j > 0 else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run(str(text))
            r.font.size = Pt(font_size)
    return table


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.space_before = Pt(4 if level == 1 else 2)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.font.color.rgb = RGBColor.from_string(NAVY if level == 1 else TEAL)


def add_body(doc: Document, text: str, bold_lead: str | None = None, size=9.3, after=4) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.12
    if bold_lead and text.startswith(bold_lead):
        r = p.add_run(bold_lead)
        r.bold = True
        rest = text[len(bold_lead):]
        p.add_run(rest)
    else:
        p.add_run(text)
    for r in p.runs:
        r.font.size = Pt(size)


def add_equation(doc: Document, equation: str, note: str = "") -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(equation)
    r.font.name = "Cambria Math"
    r.font.size = Pt(10.2)
    if note:
        rn = p.add_run(f"    {note}")
        rn.font.name = "Arial"
        rn.font.size = Pt(8.2)
        rn.font.color.rgb = RGBColor.from_string(GRAY)


def add_caption(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.italic = True
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(GRAY)


def add_page_number(section) -> None:
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run("Step-Feed AI design study  |  ")
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(GRAY)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    p._p.append(fld)


def new_page(doc: Document) -> None:
    doc.add_page_break()


def build() -> None:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(1.25)
    sec.bottom_margin = Cm(1.25)
    sec.left_margin = Cm(1.45)
    sec.right_margin = Cm(1.45)
    add_page_number(sec)

    styles = doc.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    styles["Normal"].font.size = Pt(9.3)
    for level, size in ((1, 15), (2, 11.5)):
        st = styles[f"Heading {level}"]
        st.font.name = "Arial"
        st._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor.from_string(NAVY if level == 1 else TEAL)

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.paragraph_format.space_after = Pt(2)
    run = title.add_run("AI-Assisted Feed-Split Design for a Full-Scale Step-Feed ASP")
    run.font.name = "Arial"
    run.font.size = Pt(22)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0, 0, 0)
    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(6)
    rr = sub.add_run("Steps 1-5: real case, design-space generation, surrogate optimisation, engineering audit, and professional reflection")
    rr.font.size = Pt(10.5)
    rr.font.color.rgb = RGBColor.from_string(GRAY)

    doc.add_picture(str(OUT / "workflow.png"), width=Cm(18.0))
    add_caption(doc, "Figure 1. Partial-blind workflow. The EPA split is withheld until Step 4, where it is used as a plausibility benchmark rather than proof of optimality.")

    add_heading(doc, "Step 1  Real project and partial-blind design brief")
    add_body(
        doc,
        "The benchmark is the 2021 EPA feasibility design for a new 5 MGD San Antonio de los Buenos Treatment Plant (SABTP). The AI receives the real hydraulic, organic and equipment limits, but the actual four-zone influent split is withheld. Its task is narrowly defined: select the normal-operation primary-effluent fractions f₁...f₄ for the existing four equal-volume zones. This avoids pretending that a feed-split optimiser is a complete activated-sludge design.",
    )
    basis = RESULTS["basis"]
    add_table(
        doc,
        ["Design item", "Value supplied to AI", "Source or derivation"],
        [
            ["Average / peak flow", "5.0 / 12.5 MGD", "EPA Tables 2-1 and 2-7"],
            ["Secondary-influent BOD₅ load", "11,700 lb/d", "EPA Table 2-7"],
            ["Calculated S₀", f"{basis['S0_design_mg_L']:.1f} mg/L", "11,700/(8.34×5.0)"],
            ["Aeration volume", "2.0 MG total; four equal aggregate zones", "Two 1.0-MG reactors"],
            ["MLSS and RAS ratio", "3,000 mg/L; R = 2.1/5 = 0.42", "EPA Table 2-7"],
            ["O₂ required / supplied", "15,400 / 15,600 lb/d", "EPA Table 2-7"],
            ["Performance screen", "BOD₅ ≤ 15 mg/L", "Conservative screening target"],
        ],
        [6.0, 5.5, 6.5],
        8.2,
    )
    add_body(doc, "Independent design checks:", bold_lead="Independent design checks:", after=1)
    add_equation(doc, "θ = 24V/Q = 24(2.0)/5.0 = 9.6 h")
    add_equation(doc, "Lᵥ = QS₀/[133.681V] = 43.76 lb BOD₅ d⁻¹ (10³ ft³)⁻¹")
    add_equation(doc, "F/M = QS₀/(VX) = 0.234 d⁻¹")
    add_body(doc, "These values fall inside the cited Step Aeration screening ranges of 6-8 h, 30-50 lb BOD₅ d⁻¹ per 1,000 ft³, and F/M = 0.17-0.50, except that the project deliberately provides 9.6 h for added treatment capacity [2].", size=8.6)

    add_heading(doc, "Step 2  Mechanistic label generator and design-space coverage")
    add_body(doc, "The design-space generator uses a transparent four-CSTR steady-state model. It is a screening model for soluble BOD and oxygen distribution; it does not replace ASM calibration, dynamic DO transfer, settling or sludge-blanket analysis.")
    add_heading(doc, "2.1  Key equations", level=2)
    formulas = [
        ["Split simplex", "Σᵢ₌₁⁴ fᵢ = 1;  0.05 ≤ fᵢ ≤ 0.60", "Normal-mode valve envelope"],
        ["Cumulative flow", "qᵢ = Q(R + Σⱼ₌₁ⁱ fⱼ)", "RAS enters Zone 1"],
        ["Zone BOD balance", "0 = qᵢ₋₁Sᵢ₋₁ + fᵢQS₀ − qᵢSᵢ − κVᵢSᵢ", "For Zone 1, q₀S₀ is replaced by RQS₄"],
        ["Matrix solution", "A(f,Q,R,κ,V)S = b(f,Q,S₀)", "Solves S₁...S₄ simultaneously"],
        ["BOD removed", "ΔLᵢ = 8.34κVᵢSᵢ", "lb BOD₅/d"],
        ["Zone oxygen", "Oᵢ = 1.1ΔLᵢ + Obackground/4", "1.1 lb O₂/lb peak BOD screen [2]"],
        ["Peak and balance", "P = max(Oᵢ)/mean(Oᵢ);  CV = σ(Oᵢ)/mean(Oᵢ)", "Lower values are easier to aerate"],
        ["Hydraulic checks", "θ = 24V/Q;  Lᵥ = 8.34QS₀/(133.681V);  F/M = QS₀/(VX)", "Global feasibility guards"],
    ]
    add_table(doc, ["Purpose", "Equation", "Use"], formulas, [3.3, 9.2, 5.5], 8.0)
    add_body(doc, "Calibration boundary. κ = Q(S₀−Sₑ)/(VSₑ) = 61.27 d⁻¹ is obtained from an aggregate one-point balance using the EPA-reported influent load, volume and 11 mg/L modelled effluent; the four-zone feed split is not used. κ includes the effects of active biomass and mixing and must not be interpreted as k_d. This permits relative feed-split comparison but does not independently validate absolute predictions.", bold_lead="Calibration boundary.", size=8.7)

    add_heading(doc, "2.2  Fixed-test convergence and model selection", level=2)
    add_body(doc, "Four feed fractions have only three independent degrees of freedom. A low-discrepancy Halton sequence was mapped to the simplex, while Q, S₀ and R varied over 3.5-8.0 MGD, 200-360 mg/L and 0.30-0.60. Every training size was evaluated against the same independent 2,048-case test set over five training blocks. This removes the changing-test-set artefact in the first draft.")
    add_table(
        doc,
        ["Cases", "BOD RMSE mean ± SD", "Zone-O₂ RMSE mean ± SD", "Split change vs 8,192"],
        [[f"{r['n']:,}", f"{r['bod_rmse_mean']:.4f} ± {r['bod_rmse_sd']:.4f}", f"{r['zone_o2_rmse_mean']:.2f} ± {r['zone_o2_rmse_sd']:.2f}", f"{r['split_l1_pp_mean']:.2f} percentage points"] for r in BENCH["learning_curve"]],
        [2.5, 5.2, 5.5, 4.6],
        8.1,
    )
    add_body(doc, "From 4,096 to 8,192 labels, BOD and zone-O₂ RMSE improve by only 0.6% and 0.9%. The unconstrained weighted-objective recommendation is unchanged across all tested sizes, so 4,096 is retained as a conservative stopping point rather than claimed as a unique minimum.", size=8.5)
    add_table(
        doc,
        ["Candidate surrogate at 4,096 labels", "BOD RMSE", "Zone-O₂ RMSE", "Decision"],
        [[m["model"], f"{m['bod_rmse']:.3f}", f"{m['zone_o2_rmse']:.1f}", "Selected" if m["model"] == "Polynomial ridge degree 3" else "Benchmark only"] for m in BENCH["models"]],
        [7.0, 3.0, 3.4, 4.4],
        7.7,
    )
    add_body(doc, "The cubic ridge model is selected because the deterministic response surface is smooth and it gives the lowest errors with explicit coefficients. kNN and the RBF model remain useful comparators; using several algorithms here means benchmarking them, not averaging incompatible answers.", size=8.4)

    add_heading(doc, "Step 3  Machine-learning surrogate and first AI design")
    add_body(doc, "The selected method is supervised multi-output regression: the mechanistic model generates labels, and a cubic polynomial ridge model learns a fast surrogate. Inputs are x = [f₁,f₂,f₃,Q,S₀,R], with f₄ = 1 − f₁ − f₂ − f₃. Outputs are Sₑ, four zone oxygen demands and total oxygen demand. Halton sampling is design-of-experiments, not machine learning.")
    add_equation(doc, "ŷ = Φ(x)β,  where Φ contains all terms through degree 3")
    add_equation(doc, "β = (ΦᵀΦ + λI)⁻¹Φᵀy,  λ = 10⁻⁶")
    add_equation(doc, "J = 0.50(Sₑ/15) + 0.30P + 0.15CV + 0.05(Ototal/15,600)")
    add_body(doc, "The weights are explicit engineering preferences, not learned facts. The surrogate evaluates 14,740 normal-mode splits from 32,768 low-discrepancy candidates, after which the best 200 are recomputed with the mechanistic model.", size=8.8)
    add_heading(doc, "Where AI creativity appears", level=2)
    add_body(doc, "AI provides divergent alternative generation: it searches the continuous four-way split, exposes low-BOD alternatives and constructs a capacity-response frontier. Engineering review supplies the missing equipment meaning; AI does not invent biological laws or unreported diffuser limits.", size=8.5)
    add_body(doc, "No single colour can faithfully encode a four-part feed split. The final view therefore keeps candidates neutral, uses red only to diagnose the Zone-4-controlled line, and uses touching stacked columns to show the continuous four-zone oxygen allocation as the allowable local-zone maximum C changes.", size=8.2)
    doc.add_picture(str(OUT / "capacity_value_curve.png"), width=Cm(12.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_caption(doc, "Figure 2. Panel A shows the design cloud; the red diagonal is only the Zone-4-controlled subset. Panel B enlarges the minimum-BOD capacity frontier against the continuous local limit C. Panel C stacks the four zones' actual oxygen demands at each C and overlays calculable annual oxygen-transfer electricity cost. The stack is demand, not four independently enlarged installed capacities; beyond the knee, total oxygen and cost plateau.")
    first = RESULTS["nominal_optimum"]
    add_table(
        doc,
        ["AI Round 1 recommendation", "Predicted result", "Why it initially looks attractive"],
        [["f = 30.9 / 26.9 / 30.2 / 12.0%", f"Sₑ = {first['se']:.2f} mg/L", "Lower BOD than the 15 mg/L screen"], ["Total O₂ = 15,598 lb/d", f"Peak factor = {first['peak_factor']:.3f}", "Uses installed total oxygen capacity"], ["Zone O₂ = 4,426 / 4,113 / 4,420 / 2,638 lb/d", "Zones 1 and 3 carry most load", "A non-obvious split found in seconds"]],
        [6.6, 4.8, 6.6],
        8.2,
    )
    add_body(doc, "Why this pattern emerges. Reducing f₄ gives late-entering BOD less opportunity to escape untreated; raising f₁ gives longer reaction time, while distributing substantial flow to Zones 2-3 limits the oxygen peak. The exact difference between f₂ and f₃ is an optimiser result, not a general rule that step-feed fractions must decrease downstream.", bold_lead="Why this pattern emerges.", size=8.3)

    add_heading(doc, "Step 4  Engineering correction, capacity sensitivity and reveal")
    add_body(doc, "Audit correction. The EPA source reports 15,600 lb O₂/d of total supply but no 3,900 lb O₂/d hardware limit for each zone. Dividing the total by four was an analyst-imposed assumption. Because the model uses four equal zones and total demand is already close to total supply, that assumption nearly forces equal zone demand and therefore biases the solution toward equal feed. It is withdrawn as a pass/fail constraint and retained only as one illustrative sensitivity case.", bold_lead="Audit correction.", size=8.9)
    add_body(doc, "The revised analysis treats local capacity C as unknown and repeatedly minimises effluent BOD while retaining the reported total-oxygen limit, normal split bounds and the global hydraulic/loading screens. Each point is seeded from 131,072 low-discrepancy splits and refined by pairwise continuous feed transfers before mechanistic verification.", size=8.7)
    add_equation(doc, "Sₑ*(C) = min_f Sₑ(f)")
    add_equation(doc, "subject to  maxᵢOᵢ(f) ≤ C,  Ototal(f) ≤ 15,600,  Σfᵢ = 1,  0.05 ≤ fᵢ ≤ 0.60")

    def frontier_at(capacity: float) -> dict:
        return min(FRONTIER, key=lambda row: abs(row["capacity_lb_d"] - capacity))

    reveal = RESULTS["equal_split_reveal"]
    scenarios = [frontier_at(c) for c in (3850, 3900, 4100, 4200, 4400)]
    add_table(
        doc,
        ["Illustrative local C", "Minimum Sₑ", "Mechanistically refined feed split (%)", "Total O₂ demand"],
        [[
            f"{r['capacity_lb_d']:,.0f} lb/d",
            f"{r['se_mg_L']:.2f} mg/L",
            "/".join(f"{100*r[f'f{i}']:.1f}" for i in range(1, 5)),
            f"{r['total_o2_lb_d']:,.0f} lb/d",
        ] for r in scenarios],
        [3.7, 3.3, 7.0, 4.0],
        8.0,
    )
    add_heading(doc, "Cost consequence of raising local C", level=2)
    add_equation(doc, "TAC(C) = a CAPEXlocal(C) + O&Mlocal(C) + 365(0.453592 O₂,total(C))pe/ηO₂")
    cost_rows = []
    for r in scenarios:
        delta_o2 = r["total_o2_lb_d"] - reveal["o2_total"]
        mwh_low = 365.0 * 0.453592 * r["total_o2_lb_d"] / 2.2 / 1000.0
        mwh_high = 365.0 * 0.453592 * r["total_o2_lb_d"] / 1.2 / 1000.0
        delta_cost_low = 365.0 * 0.453592 * delta_o2 / 2.2 * 0.10
        delta_cost_high = 365.0 * 0.453592 * delta_o2 / 1.2 * 0.10
        cost_rows.append([
            f"{r['capacity_lb_d']:,.0f}",
            f"{r['total_o2_lb_d']:,.0f}",
            f"{mwh_low:,.0f}-{mwh_high:,.0f}",
            f"${mwh_low*0.1:.1f}k-${mwh_high*0.1:.1f}k",
            "baseline" if abs(delta_o2) < 0.5 else f"+${delta_cost_low/1000:.1f}k-${delta_cost_high/1000:.1f}k",
        ])
    add_table(
        doc,
        ["C (lb/d)", "Total O₂ demand", "Total electricity (MWh/y)", "Energy cost at $0.10/kWh", "Change vs C=3,850"],
        cost_rows,
        [2.2, 3.3, 4.2, 4.8, 3.5],
        7.6,
    )
    add_body(doc, "The reported total supply remains 15,600 lb O₂/d. The table therefore reports the calculable oxygen-transfer electricity component, using ηO₂ = 1.2-2.2 kg O₂/kWh, rather than pretending it is complete lifecycle cost. From C = 3,850 to 4,400 lb/d, modelled total oxygen demand rises only 1.3%, so annual energy cost rises about $1.5k-$2.8k. The unknown term is local-distribution CAPEX/O&M: diffuser density and fouling, alpha factor, basin depth, header loss, valve Cv, blower curve and spare turndown are not reported. If the existing blower can redistribute air, no additional total blower capacity is implied.", size=7.8)
    add_body(doc, "Value of the blue frontier. From C = 3,850 to about 4,400 lb/d, added local aeration capacity unlocks progressively more front-loaded designs and reduces predicted BOD from 11.0 to about 6.64 mg/L. Beyond roughly 4,400 lb/d the curve becomes nearly horizontal because the reported 15,600 lb/d total oxygen supply, rather than local distribution, becomes binding. The knee therefore identifies the point beyond which redistributing or enlarging one zone's aeration system has little value unless total supply also increases.", bold_lead="Value of the blue frontier.", size=8.6)

    add_table(
        doc,
        ["Metric", "Weighted-objective AI", "EPA reveal", "Interpretation"],
        [
            ["Feed split (%)", "30.9/26.9/30.2/12.0", "25/25/25/25", "AI is more front-loaded"],
            ["Effluent BOD₅ (mg/L)", f"{first['se']:.2f}", f"{reveal['se']:.2f}", "Modelled, not field-validated"],
            ["Peak zone O₂ demand", f"{max(first['o2_zones']):,.0f} lb/d", f"{max(reveal['o2_zones']):,.0f} lb/d", "Actual zone capacity unknown"],
            ["Total O₂ demand", f"{first['o2_total']:,.0f} lb/d", f"{reveal['o2_total']:,.0f} lb/d", "Both within reported total"],
        ],
        [3.6, 4.5, 4.0, 5.8],
        7.9,
    )
    add_body(doc, "Reveal interpretation. EPA selected 25% to each equal-volume quadrant to approximately even out organic loading [1]. The AI result is not disproved, but it cannot be declared constructible without zone-level diffuser, header, valve, DO and alpha-factor data. Conversely, agreement obtained by imposing 15,600/4 would be circular. The reveal is therefore a plausibility benchmark and a prompt for missing-data collection, not independent validation of optimality.", bold_lead="Reveal interpretation.", size=8.5)
    add_heading(doc, "Capacity guardrail test", level=2)
    stress = RESULTS["stress_optimum"]
    add_body(doc, f"For a deliberately adverse case (Q = 7.5 MGD, S₀ = 320 mg/L), the optimiser returns no feasible split instead of a false optimum: θ = {stress['equal_split_screen']['hrt']:.1f} h, volumetric loading = {stress['equal_split_screen']['loading']:.1f} lb BOD₅ d⁻¹ per 1,000 ft³ and O₂ demand ≈ {stress['equal_split_screen']['o2_total']:,.0f} lb/d. The loading criterion requires at least {stress['minimum_volume_from_50lb_loading_MG']:.2f} MG, and the screening oxygen deficit is about {stress['additional_oxygen_capacity_lb_d']:,.0f} lb/d. Changing feed fractions cannot repair insufficient total volume or aeration capacity.", size=8.5)

    add_heading(doc, "Step 5  Overall evaluation and professional reflection")
    add_heading(doc, "5.1  Integrated engineering judgement", level=2)
    add_body(doc, "Overall conclusion. AI was effective as a disciplined alternative generator, not as an autonomous designer. It searched 14,740 feasible normal-mode splits in seconds, exposed the local-capacity/BOD trade-off, and identified the knee near C = 4,400 lb O₂/d. The engineering audit was equally important: it removed the invented 3,900 lb/d-per-zone constraint, rejected an infeasible stress case, and showed that the apparent optimum depends on unreported air-distribution hardware. The defensible output is therefore a design envelope and test plan, not a guaranteed effluent value.", bold_lead="Overall conclusion.", size=8.7)
    add_table(
        doc,
        ["Evidence from Steps 1-4", "Engineering meaning", "Decision"],
        [
            ["4,096 labels; fixed-test error plateau; stable recommended split", "The cubic ridge surrogate is adequate for rapid screening inside the sampled domain", "Retain mechanistic recomputation for every shortlisted design"],
            ["C: 3,850→4,400 lb/d; BOD₅: 11.00→6.64 mg/L", "Local air-distribution capacity has value until total O₂ supply binds", "Do not increase C beyond the knee without increasing total supply"],
            ["Energy-only increase ≈ $1.5k-$2.8k/y; retrofit cost unknown", "Electricity is not the controlling uncertainty", "Obtain blower, header, valve and diffuser quotations before lifecycle ranking"],
            ["Adverse case has no feasible split", "Feed redistribution cannot replace missing basin or blower capacity", "Keep hard hydraulic, loading and oxygen guardrails outside the ML model"],
        ],
        [5.8, 6.5, 5.3],
        7.6,
    )
    add_body(doc, "Recommended next design state. Use the C = 4,200 lb/d solution (28.7/28.0/28.0/15.4%) as a conservative commissioning hypothesis because it captures most of the predicted BOD benefit while preserving margin below the reported total oxygen supply. Specify adjustable feed gates, zone air-flow measurement, DO sensors and valve-position logging so the plant can test progressively more front-loaded operation toward the C ≈ 4,400 lb/d solution. Advance only if oxygen-transfer testing and blower/header calculations show that the local load can be delivered without unacceptable pressure loss, loss of turndown or downstream oxygen limitation.", bold_lead="Recommended next design state.", size=8.4)

    new_page(doc)
    add_heading(doc, "5.2  Check against current engineering evidence", level=2)
    add_body(doc, "The real project has moved beyond the 2021 feasibility snapshot. USIBWC reported that officials verified operation of the newly constructed SAB WWTP on 29 May 2025 [3]. Minute 333 subsequently called for technical and financial study of expansion from 18.26 to 43.37 MGD and for transparent real-time flow and effluent-quality monitoring [4]. Consequently, this 5 MGD exercise should be read as a reproducible historical design benchmark; it cannot represent the current as-built plant without updated process, equipment and monitoring data.", size=8.3)
    add_body(doc, "Recent full-scale AI studies support the workflow but also raise the validation standard. A 2025 real-scale PN/A digital twin reported >95% model accuracy, 16.7% electricity reduction at about 400 m³/d and about $19,724/y operating-cost reduction [5]. A separate 2025 full-scale study compared five aeration controllers; its LSTM-fuzzy expert controller held DO within ±0.5 mg/L for 53 consecutive days, reduced DO overshoot events by >90%, and reported about $180,000 lower OPEX over six months [6]. These results are not transferable performance guarantees for step-feed ASP; they show that credible AI claims require plant sensors, explicit control logic, sustained trials and comparison with a real baseline.", size=8.2)

    add_heading(doc, "5.3  Professional reflection", level=2)
    add_body(doc, "This exercise changed how we would use AI as environmental engineers. Its main creative contribution was not producing one unusual split, but rapidly constructing alternatives and revealing a frontier that we would not obtain from a single hand calculation. Its productivity contribution was automating sampling, screening, surrogate benchmarking, plotting and sensitivity analysis while leaving an auditable calculation trail.", size=8.4)
    add_body(doc, "The most important professional lesson came from the error. Dividing 15,600 lb O₂/d by four looked reasonable, but it silently converted a total plant value into four local hardware limits and biased the answer toward equal feed. A polished result was therefore less valuable than an assumption register, dimensional checks and a deliberate reveal against the EPA design. In future work, we would require every AI recommendation to state its data source, validity range, governing constraints, uncertainty and a falsification test before it enters a design decision.", size=8.4)
    add_body(doc, "Our professional responsibility remains with the engineer. We would use AI to widen the option set and accelerate calculations, but retain human approval for model scope, safety factors, constructability, commissioning and regulatory compliance. Before field deployment, the tool should run in shadow mode, be challenged with peak-flow and sensor-failure cases, include manual override and rollback, and be monitored for drift. Used this way, AI strengthens engineering judgement; used as an unexplained answer generator, it can make an unsupported assumption appear precise.", size=8.4)

    add_heading(doc, "References", level=2)
    add_body(doc, "[1] U.S. EPA, Project 8: Upgrade San Antonio de los Buenos Wastewater Treatment Plant, Addendum to the Feasibility Analysis, 19 Nov 2021, pp. 3-6. https://www.epa.gov/system/files/documents/2021-12/usmca-feasibility-analysis_project-8_upgrade-sab-wwtp-addendum.pdf", size=7.6, after=1)
    add_body(doc, "[2] Oklahoma Administrative Code 252:656, Appendix A and Section 16-1: Step Aeration screening ranges and oxygen criterion. https://www.law.cornell.edu/regulations/oklahoma/OAC-252-656-app-A and https://okrules.elaws.us/oac/252%3A656-16-1", size=7.6, after=1)
    add_body(doc, "[3] USIBWC, Moving Fast and Fixing Things: USIBWC Focused on Infrastructure Improvements and Tijuana River Pollution, 12 Jun 2025. https://www.ibwc.gov/wp-content/uploads/2025/06/MOVING-FAST-AND-FIXING-THINGS-USIBWC-FOCUSED-ON-INFRASTRUCTURE-IMPROVEMENTS-AND-TIJUANA-RIVER-POLLUTION.pdf", size=7.4, after=1)
    add_body(doc, "[4] U.S. EPA, Minute No. 333: San Antonio de los Buenos expansion feasibility and real-time binational monitoring actions. https://www.epa.gov/sustainable-water-infrastructure/minute-no-333", size=7.4, after=1)
    add_body(doc, "[5] Heo, S.K. et al. (2025). Real-scale demonstration of digital twins-based aeration control policy optimization in partial nitritation/Anammox process. Desalination 593, 118235. https://doi.org/10.1016/j.desal.2024.118235", size=7.4, after=1)
    add_body(doc, "[6] Xiong, Z. et al. (2025). Machine Learning-Assisted Expert Control in Wastewater Aeration Treatment Process Application. ACS ES&T Engineering 5(11), 3140-3152. https://doi.org/10.1021/acsestengg.5c00493", size=7.4, after=1)
    doc.save(DOCX)
    print(DOCX)


if __name__ == "__main__":
    build()
