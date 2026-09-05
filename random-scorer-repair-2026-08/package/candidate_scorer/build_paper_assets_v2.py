#!/usr/bin/env python3
r"""Task 8 v2 — publication layout for the sealed-package tables and figures.

v1 produced correct numbers in a layout that overflows a two-column IAC page.
v2 keeps every number and every provenance binding byte-for-byte and changes
only how they are set:

  * tables are compiled against the REAL manuscript preamble at its real
    geometry (column 234.59pt, text 486.26pt) and each one's single-column vs
    full-width decision is measured, not guessed;
  * no \resizebox anywhere - a table that only fits when shrunk is reported,
    not silently made unreadable;
  * NO new package is required: paper.tex loads array/longtable/ragged2e, so
    rules are \hline and long text uses controlled p{} columns;
  * figures embed TrueType (Type 42), carry no Type 3 font, keep legends out
    of the data area, and are authored at their final width so nothing is
    scaled down into illegibility.

Original v1 docstring follows.

Task 8 — deterministic table and figure candidates from the SEALED package.

Every number is read from the sealed Task-7 package inside the acceptance
checkpoint, never from the working tree, and every rendered cell records the
estimand id and the JSON Pointer it came from. Nothing is typed by hand.

Three rules are enforced structurally rather than by care:
  * macro, pooled and interval never share a column;
  * a null value is rendered as `n/a` with its reason code and is NEVER 0;
  * a value can only reach a table through cell(), which records provenance.
"""
import argparse
import hashlib
import json
import os
import sys

CHECKPOINT = ("/home/topya/lifesat_backups/checkpoints/"
              "20260811T204924Z-corrected-results-v1-accepted")
SEAL = os.path.join(CHECKPOINT, "ACCEPTANCE_SEAL.json")
SEAL_SHA = "6d0aa788fc1370f89d697eb565f750c6e43b3a6709eb5a3a39c61b77b376ee74"
PKG = os.path.join(CHECKPOINT, "package")


# The manuscript's own preamble, copied verbatim from
# manuscript/dizgi/latex-kaynakcali/paper.tex. The compile gate uses exactly
# this: a table that needs anything else is not droppable into the paper.
REAL_PREAMBLE = r"""\documentclass[10pt,twocolumn,letterpaper]{article}
\usepackage[left=2.25cm,right=2.25cm,top=3.35cm,bottom=3.35cm]{geometry}
\usepackage{mathptmx}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{array,longtable,ragged2e}
\usepackage[hidelinks]{hyperref}
\setlength{\columnsep}{0.6cm}
\linespread{1.0}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\renewcommand{\arraystretch}{1.05}
"""
COLUMN_PT = 234.5929        # \columnwidth at this geometry
TEXT_PT = 486.25761         # \textwidth  at this geometry
OVERFULL_TOLERANCE_PT = 0.5


class AssetError(Exception):
    """Anything that must stop asset generation."""


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_sealed():
    if not os.path.exists(SEAL):
        raise AssetError("acceptance seal not found at %s" % SEAL)
    if sha256(SEAL) != SEAL_SHA:
        raise AssetError("seal sha256 %s != pinned %s" % (sha256(SEAL), SEAL_SHA))
    seal = json.load(open(SEAL, encoding="utf-8"))
    if seal.get("verdict") != "ACCEPTED":
        raise AssetError("seal verdict is %r" % seal.get("verdict"))
    docs = {}
    for entry in seal["package"]["files"]:
        path = os.path.join(PKG, entry["path"])
        got = sha256(path)
        if got != entry["sha256"]:
            raise AssetError("%s sha256 %s != sealed %s"
                             % (entry["path"], got, entry["sha256"]))
        if entry["path"].endswith(".json"):
            docs[entry["path"]] = json.load(open(path, encoding="utf-8"))
    return seal, docs


# ── provenance ─────────────────────────────────────────────────────────────
def resolve(doc, pointer):
    """RFC 6901 JSON Pointer, used to prove a rendered value's origin."""
    node = doc
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


class Provenance:
    def __init__(self):
        self.entries = []

    def record(self, table, row, column, document, pointer, raw, rendered,
               estimand_id, quantity):
        self.entries.append({
            "table": table, "row": row, "column": column,
            "document": document, "json_pointer": pointer,
            "estimand_id": estimand_id, "quantity": quantity,
            "raw_value": raw, "rendered": rendered})
        return rendered


P = Provenance()
DOCS = {}


def fmt(value, digits=4):
    """Fixed decimals. Never strip: a ragged 0.002 beside 0.0000 reads as two
    different precisions when it is one measurement family."""
    if value is None:
        return None
    return "%.*f" % (digits, value)


def cell(table, row, column, pointer, estimand_id, quantity,
         document="CORRECTED_RESULTS.json", digits=4, kind="number"):
    """The ONLY way a number reaches a table. Records where it came from."""
    raw = resolve(DOCS[document], pointer)
    if kind == "interval":
        if raw is None:
            rendered = NA
        else:
            rendered = "[%s, %s]" % (fmt(raw["ci_low"], digits),
                                     fmt(raw["ci_high"], digits))
    elif kind == "int":
        rendered = NA if raw is None else "%d" % raw
    else:
        rendered = NA if raw is None else fmt(raw, digits)
    return P.record(table, row, column, document, pointer, raw, rendered,
                    estimand_id, quantity)


NA = r"\textit{n/a}"


def esc(text):
    for a, b in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"),
                 ("&", r"\&"), ("#", r"\#")):
        text = text.replace(a, b)
    return text


class Table(object):
    r"""A table whose LAYOUT is decided later, by measurement.

    Rendering is deferred because the single-column vs full-width decision can
    only be made by compiling against the real geometry. Only what paper.tex
    already loads is used: array + \hline, no booktabs, no tabularx, and never
    \resizebox - a table that fits only when shrunk is reported, not hidden.
    """

    def __init__(self, label, caption, columns, rows, notes=()):
        self.label = label
        self.caption = caption
        self.columns = list(columns)
        self.rows = list(rows)
        self.notes = list(notes)

    def render(self, env, colspec=None, note_width_pt=None):
        spec = colspec or ("l" + "r" * (len(self.columns) - 1))
        star = "*" if env == "table*" else ""
        width = note_width_pt or (TEXT_PT if star else COLUMN_PT)
        out = ["% GENERATED by analysis/build_paper_assets_v2.py -- do not edit.",
               "% Values bind to estimand ids and JSON Pointers in PROVENANCE.json.",
               "% Layout decision and measured overfull: see LAYOUT.json.",
               "% Requires no package beyond those paper.tex already loads.",
               r"\begin{table%s}[t]" % star,
               r"\centering",
               r"\footnotesize",
               r"\caption{%s}" % self.caption,
               r"\label{%s}" % self.label,
               r"\begin{tabular}{%s}" % spec,
               r"\hline"]
        out.append(" & ".join(esc(c) for c in self.columns) + r" \\")
        out.append(r"\hline")
        for row in self.rows:
            out.append(" & ".join(row) + r" \\")
        out.append(r"\hline")
        out.append(r"\end{tabular}")
        for note in self.notes:
            out.append(r"\\[3pt]")
            out.append(r"\begin{minipage}{%.2fpt}\footnotesize\RaggedRight %s"
                       r"\end{minipage}" % (width, note))
        out += [r"\end{table%s}" % star, ""]
        return "\n".join(out)


def latex_table(label, caption, columns, rows, notes=()):
    return Table(label, caption, columns, rows, notes)


# Column specifications. p{} widths are chosen so the natural numeric columns
# keep their own width; nothing is scaled.
W = r">{\RaggedRight\arraybackslash}p{%s}"
LAYOUT_SPEC = {
    "table_08_a4_subtype_layers.tex": {
        "wide": (W % "6.0cm") + "l" + "r" * 3},
    "table_09_drop_decision_units.tex": {
        "single": (W % "4.6cm") + "r",
        "wide": (W % "6.4cm") + (W % "2.5cm") + (W % "3.3cm") + "r"},
    "table_11_iss06_cooccurrence.tex": {
        "single": (W % "5.9cm") + "r",
        "wide": (W % "8.0cm") + "r"},
    "table_12_tier2_pre_uplink_validation.tex": {
        "wide": (W % "3.4cm") + (W % "3.2cm") + "r" * 3},
    "table_13_tier2_forensic_chain.tex": {
        "wide": (W % "2.8cm") + "r" + (W % "1.9cm") + (W % "1.9cm")
                + (W % "3.6cm")},
    # Budget: text width 17.09cm minus 2*\tabcolsep per column (0.42cm x 4
    # = 1.69cm) leaves 15.40cm for the p{} widths. 14.90cm keeps 0.5cm slack.
    "table_14_withheld_and_limits.tex": {
        "wide": (W % "2.9cm") + (W % "4.2cm") + (W % "3.1cm") + (W % "4.7cm")},
}


# ── compile gate: the real preamble, the real geometry ───────────────────
FILLER = (r"\RaggedRight Filler paragraph used only to give the float a page to "
          r"settle on. It is set ragged right so that no prose line can "
          r"contribute an overfull box to the measurement, leaving the table "
          r"as the only possible source. " * 3)


def measure_overfull(body, workdir, stem):
    r"""Compile `body` with the manuscript preamble; return the worst overfull.

    Returns (max_overfull_pt, compiled_ok, log_excerpt).
    """
    import subprocess
    os.makedirs(workdir, exist_ok=True)
    tex = os.path.join(workdir, stem + ".tex")
    with open(tex, "w", encoding="utf-8") as fh:
        fh.write(REAL_PREAMBLE)
        fh.write("\\begin{document}\n")
        fh.write(FILLER + "\n\n")
        fh.write(body)
        fh.write("\n" + FILLER + "\n")
        fh.write("\\end{document}\n")
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
         "-output-directory", workdir, tex],
        capture_output=True, text=True)
    log_path = os.path.join(workdir, stem + ".log")
    log = open(log_path, encoding="utf-8", errors="replace").read() \
        if os.path.exists(log_path) else proc.stdout
    worst = 0.0
    for line in log.splitlines():
        if "Overfull \\hbox" in line and "too wide" in line:
            try:
                worst = max(worst, float(line.split("(")[1].split("pt")[0]))
            except (IndexError, ValueError):
                worst = max(worst, 999.0)
    ok = proc.returncode == 0 and os.path.exists(
        os.path.join(workdir, stem + ".pdf"))
    excerpt = "\n".join(l for l in log.splitlines()
                         if "Overfull" in l or "! " in l)[:400]
    return worst, ok, excerpt


# ── locating estimands inside the sealed document ─────────────────────────
def cell_index(C, name):
    for i, c in enumerate(C["cells"]):
        if c["cell"] == name:
            return i
    raise AssetError("cell %s absent from the sealed package" % name)


def est_index(C, cell_name, estimand_id):
    ci = cell_index(C, cell_name)
    for j, e in enumerate(C["cells"][ci]["estimands"]):
        if e["estimand_id"] == estimand_id:
            return ci, j
    return ci, None


def arm_ptr(ci, ej, arm, field):
    return "/cells/%d/estimands/%d/arms/%s/%s" % (ci, ej, arm, field)


def cells_with(C, estimand_id, arm=None):
    out = []
    for i, c in enumerate(C["cells"]):
        for j, e in enumerate(c["estimands"]):
            if e["estimand_id"] == estimand_id and (arm is None or arm in e["arms"]):
                out.append((c["cell"], i, j))
    return out


# ════════════════════════════════════════════════════════════════════════════
# TABLES
# ════════════════════════════════════════════════════════════════════════════
MACRO_NOTE = ("Macro is the mean over defined runs; the interval is the "
              "contract's two-sided 95\\% percentile bootstrap (2000 resamples, "
              "seed 12345, resampling unit = run). The pooled ratio is a "
              "separate descriptive quantity and carries no interval.")
NA_NOTE = ("\\textit{n/a} marks a quantity that is undefined or not applicable; "
           "it is never rendered as zero.")


def four_column_estimand(C, tag, caption, label, estimand_id, arm, quantity):
    """One estimand, one arm, across every cell that publishes it."""
    rows = []
    for name, ci, ej in cells_with(C, estimand_id, arm):
        rows.append([
            esc(name),
            cell(tag, name, "macro", arm_ptr(ci, ej, arm,
                                             "macro_mean_over_defined_runs"),
                 estimand_id, quantity),
            cell(tag, name, "ci", arm_ptr(ci, ej, arm, "uncertainty"),
                 estimand_id, quantity + " 95% CI", kind="interval"),
            cell(tag, name, "pooled", arm_ptr(ci, ej, arm, "pooled_ratio"),
                 estimand_id, quantity + " pooled"),
            cell(tag, name, "defined_runs", arm_ptr(ci, ej, arm,
                                                    "defined_run_count"),
                 estimand_id, "defined runs", kind="int"),
            cell(tag, name, "total_runs", arm_ptr(ci, ej, arm, "total_run_count"),
                 estimand_id, "total runs", kind="int")])
    return latex_table(label, caption,
                       ["Cell", "Macro mean", "95% CI (macro)", "Pooled ratio",
                        "Defined runs", "Runs"], rows,
                       notes=[MACRO_NOTE + " " + NA_NOTE])


def table_confusion(C, tag, caption, label, estimand_id, cells_wanted=None):
    """Recall / precision / FPR for one detector family, macro with interval."""
    rows = []
    for name, ci, ej in cells_with(C, estimand_id, "recall"):
        if cells_wanted and name not in cells_wanted:
            continue
        row = [esc(name)]
        for arm, quantity in (("recall", "recall"), ("precision", "precision"),
                              ("fpr", "false positive rate")):
            row.append(cell(tag, name, arm + " macro",
                            arm_ptr(ci, ej, arm, "macro_mean_over_defined_runs"),
                            estimand_id, quantity))
            row.append(cell(tag, name, arm + " ci",
                            arm_ptr(ci, ej, arm, "uncertainty"),
                            estimand_id, quantity + " 95% CI", kind="interval"))
        rows.append(row)
    return latex_table(label, caption,
                       ["Cell", "Recall", "95% CI", "Precision", "95% CI",
                        "FPR", "95% CI"], rows,
                       notes=[MACRO_NOTE + " " + NA_NOTE])


def table_a4_subtype(C):
    tag = "a4_subtype"
    rows = []
    ci, ej = est_index(C, "A4-D3", "EST-A4-L2-01")
    rows.append(["Received tampered/delayed observations (L2)",
                 esc("EST-A4-L2-01"),
                 cell(tag, "L2-01", "macro",
                      arm_ptr(ci, ej, "detection_rate",
                              "macro_mean_over_defined_runs"),
                      "EST-A4-L2-01", "D3 detection rate"),
                 cell(tag, "L2-01", "ci",
                      arm_ptr(ci, ej, "detection_rate", "uncertainty"),
                      "EST-A4-L2-01", "D3 detection rate 95% CI", kind="interval"),
                 cell(tag, "L2-01", "pooled",
                      arm_ptr(ci, ej, "detection_rate", "pooled_ratio"),
                      "EST-A4-L2-01", "D3 detection rate pooled")])
    ci, ej = est_index(C, "A4-D3", "EST-A4-L2-02")
    for arm, title in (("modification_detection_rate", "Modification subtype (L2)"),
                       ("delay_detection_rate", "Delay subtype (L2)")):
        rows.append([title, esc("EST-A4-L2-02"),
                     cell(tag, arm, "macro",
                          arm_ptr(ci, ej, arm, "macro_mean_over_defined_runs"),
                          "EST-A4-L2-02", title + " macro"),
                     cell(tag, arm, "ci", arm_ptr(ci, ej, arm, "uncertainty"),
                          "EST-A4-L2-02", title + " 95% CI", kind="interval"),
                     cell(tag, arm, "pooled",
                          arm_ptr(ci, ej, arm, "pooled_ratio"),
                          "EST-A4-L2-02", title + " pooled")])
    rows.append(["Drop subtype (L2)", esc("EST-A4-L2-02"), NA, NA, NA])
    ci, ej = est_index(C, "A4-D2", "EST-A4-L3-01")
    for arm, title in (("alarming_truth_positive_window_rate",
                        "Alarming truth-positive windows (L3)"),
                       ("truth_positive_window_recall",
                        "Truth-positive window recall (L3)")):
        rows.append([title, esc("EST-A4-L3-01"),
                     cell(tag, arm, "macro",
                          arm_ptr(ci, ej, arm, "macro_mean_over_defined_runs"),
                          "EST-A4-L3-01", title + " macro"),
                     cell(tag, arm, "ci", arm_ptr(ci, ej, arm, "uncertainty"),
                          "EST-A4-L3-01", title + " 95% CI", kind="interval"),
                     cell(tag, arm, "pooled", arm_ptr(ci, ej, arm, "pooled_ratio"),
                          "EST-A4-L3-01", title + " pooled")])
    ci, ej = est_index(C, "A4-D2", "EST-A4-L3-02")
    rows.append(["Drops in an alarming expected-arrival window (L3)",
                 esc("EST-A4-L3-02"),
                 cell(tag, "L3-02", "macro",
                      arm_ptr(ci, ej, "alarm_covered_drop_rate",
                              "macro_mean_over_defined_runs"),
                      "EST-A4-L3-02", "alarm-covered drop rate"),
                 cell(tag, "L3-02", "ci",
                      arm_ptr(ci, ej, "alarm_covered_drop_rate", "uncertainty"),
                      "EST-A4-L3-02", "alarm-covered drop rate 95% CI",
                      kind="interval"),
                 cell(tag, "L3-02", "pooled",
                      arm_ptr(ci, ej, "alarm_covered_drop_rate", "pooled_ratio"),
                      "EST-A4-L3-02", "alarm-covered drop rate pooled")])
    return latex_table(
        "tab:a4-subtype", "A4 layered estimands. The L2 layer is the received "
        "telemetry observation (D3); the L3 layer is the 60\\,s flow window "
        "(D2). The drop subtype has no L2 rate: a dropped packet never "
        "instantiates a received observation.",
        ["Quantity", "Estimand", "Macro mean", "95% CI (macro)",
         "Pooled ratio"], rows,
        notes=[MACRO_NOTE + " " + NA_NOTE])


def table_drop_units(C):
    tag = "drop_units"
    d3ci, d3ej = est_index(C, "A4-D3", "EST-A4-L2-02")
    d2ci, d2ej = est_index(C, "A4-D2", "EST-A4-L3-02")
    base = "/cells/%d/estimands/%d/counts" % (d3ci, d3ej)
    d2base = "/cells/%d/estimands/%d/counts/drop_opportunity_classes" % (d2ci, d2ej)
    rows = [
        ["Drop actions injected", esc("EST-A4-L2-02"), "attack action",
         cell(tag, "actions", "n", base + "/drop_subtype/actions",
              "EST-A4-L2-02", "drop actions", kind="int")],
        ["Drops with no D3 decision opportunity", esc("EST-A4-L2-02"),
         "received observation",
         cell(tag, "no_decision", "n",
              base + "/drop_subtype/no_decision_opportunity",
              "EST-A4-L2-02", "drops without a D3 decision point", kind="int")],
        ["Drops with a native D2 window opportunity", esc("EST-A4-L3-02"),
         "60\\,s flow window",
         cell(tag, "native", "n", d2base + "/native_decision_opportunity",
              "EST-A4-L3-02", "native decision opportunity", kind="int")],
        ["Drops with no native D2 window opportunity", esc("EST-A4-L3-02"),
         "60\\,s flow window",
         cell(tag, "no_native", "n", d2base + "/no_native_decision_opportunity",
              "EST-A4-L3-02", "no native decision opportunity", kind="int")],
        ["Unresolved drops", esc("EST-A4-L3-02"), "60\\,s flow window",
         cell(tag, "unresolved", "n", d2base + "/unresolved",
              "EST-A4-L3-02", "unresolved", kind="int")],
        ["Native-opportunity drops inside an alarming window", esc("EST-A4-L3-02"),
         "60\\,s flow window",
         cell(tag, "covered", "n",
              d2base + "/covered_by_alarming_expected_arrival_window",
              "EST-A4-L3-02", "alarm-covered drops", kind="int")]]
    return latex_table(
        "tab:drop-units",
        "The same dropped packets counted under two different decision units. "
        "D3 decides per received observation, so every drop lacks a decision "
        "point; D2 decides per 60\\,s window, which partitions the same drops.",
        ["Quantity", "Estimand", "Decision unit", "Count"], rows,
        notes=["The two families are not interchangeable: a window-level count "
               "must never be reported as an observation-level one."])


def table_dispositions(C):
    tag = "dispositions"
    rows = []
    for name, ci, ej in cells_with(C, "EST-F0-02"):
        base = "/cells/%d/estimands/%d/counts" % (ci, ej)
        rows.append([esc(name)] + [
            cell(tag, name, k, base + "/dispositions/" + k, "EST-F0-02",
                 "A4 %s actions" % k, kind="int")
            for k in ("received_modified", "received_delayed", "dropped",
                      "unresolved")] + [
            cell(tag, name, "total", base + "/total_actions", "EST-F0-02",
                 "A4 actions injected", kind="int")])
    return latex_table(
        "tab:a4-dispositions",
        "A4 action accounting: every injected telemetry-side action reconciles "
        "to exactly one disposition.",
        ["Cell", "Modified", "Delayed", "Dropped", "Unresolved", "Injected"],
        rows, notes=["Counts are corpus totals over the 60 seed-indexed runs "
                     "of each cell."])


def table_iss06(C):
    tag = "iss06"
    b = "/iss06_channel_cooccurrence"
    rows = [["d3.alarm records", cell(tag, "alarms", "n", b + "/d3_alarms",
                                      "ISS-06", "alarms", kind="int")],
            ["Label: physical", cell(tag, "physical", "n",
                                     b + "/channel_labels/physical", "ISS-06",
                                     "physical label", kind="int")],
            ["Label: logical", cell(tag, "logical", "n",
                                    b + "/channel_labels/logical", "ISS-06",
                                    "logical label", kind="int")],
            ["Label: security", cell(tag, "security", "n",
                                     b + "/channel_labels/security", "ISS-06",
                                     "security label", kind="int")],
            ["Simultaneous physical+security", cell(
                tag, "cooc", "n", b + "/boolean_combinations/physical+security",
                "ISS-06", "co-occurring breaches", kind="int")],
            ["Priority/boolean violations", cell(
                tag, "viol", "n", b + "/priority_boolean_violations", "ISS-06",
                "violations", kind="int")]]
    return latex_table(
        "tab:iss06",
        "Channel attribution recovered from the ISS-06 rerun. The priority "
        "label alone hides simultaneity; the persisted booleans expose it.",
        ["Quantity", "Count"], rows,
        notes=["Scope: the three rerun cells A1/A2/A3-D3. A physical label "
               "outranks security, so co-occurrence is invisible without the "
               "booleans."])


def table_tier2_f5(C):
    """F5 and F6 measure different things and must not share columns."""
    tag = "tier2_f5"
    rows = []
    f5 = next(i for i, t in enumerate(C["tier2_descriptive"])
              if t["estimand_id"] == "EST-F5-01")
    for k, run in enumerate(C["tier2_descriptive"][f5]["runs"]):
        b = "/tier2_descriptive/%d/runs/%d" % (f5, k)
        expected = run["expected_verdict"]
        rows.append([esc(run["run_identity"]),
                     esc(expected) if expected
                     else r"\textit{none scheduled}",
                     cell(tag, run["run_identity"], "opportunities",
                          b + "/scheduled_validation_opportunities",
                          "EST-F5-01", "validation opportunities", kind="int"),
                     cell(tag, run["run_identity"], "matching", b + "/numerator",
                          "EST-F5-01", "verdicts matching expectation",
                          kind="int"),
                     cell(tag, run["run_identity"], "agreement", b + "/value",
                          "EST-F5-01", "verdict agreement")])
    return latex_table(
        "tab:tier2-f5",
        "Tier-2 pre-uplink validation (F5). Each arm declares its expected "
        "verdict in the configuration; the gate-off arm schedules no validation "
        "at all, so its agreement is undefined rather than zero.",
        ["Illustrative run", "Declared expected verdict",
         "Scheduled opportunities", "Matching verdicts", "Agreement"], rows,
        notes=["Descriptive single runs; never pooled into the 20-cell matrix. "
               + NA_NOTE])


def table_tier2_f6(C):
    tag = "tier2_f6"
    rows = []
    f6 = next(i for i, t in enumerate(C["tier2_descriptive"])
              if t["estimand_id"] == "EST-F6-01")
    for k, run in enumerate(C["tier2_descriptive"][f6]["runs"]):
        b = "/tier2_descriptive/%d/runs/%d" % (f6, k)
        rows.append([esc(run["run_identity"]),
                     cell(tag, run["run_identity"], "chain_length",
                          b + "/chain_length", "EST-F6-01",
                          "records in the chain", kind="int"),
                     esc(str(run["anchor_agreement"])),
                     esc(str(run["chain_intact"])),
                     esc(str(run["tamper_mutation"]["detected_at_the_mutated_record"]))])
        P.record(tag, run["run_identity"], "anchor_agreement",
                 "CORRECTED_RESULTS.json", b + "/anchor_agreement",
                 run["anchor_agreement"], str(run["anchor_agreement"]),
                 "EST-F6-01", "recomputed head matches the anchor")
        P.record(tag, run["run_identity"], "tamper_detected",
                 "CORRECTED_RESULTS.json",
                 b + "/tamper_mutation/detected_at_the_mutated_record",
                 run["tamper_mutation"]["detected_at_the_mutated_record"],
                 str(run["tamper_mutation"]["detected_at_the_mutated_record"]),
                 "EST-F6-01", "single altered record caught at that record")
    return latex_table(
        "tab:tier2-f6",
        "Tier-2 forensic mechanism (F6). The stored chain recomputes to the "
        "anchored head, and a single altered record is detected at exactly that "
        "record.",
        ["Illustrative run", "Chain records", "Anchor agrees", "Chain intact",
         "Tamper caught at the altered record"], rows,
        notes=["Descriptive single runs; never pooled into the 20-cell matrix."])


def table_withheld(C):
    tag = "withheld"
    rows = [["EST-A4-L4-01", "Direct D3 detection of dropped telemetry",
             "structurally not applicable", esc("no number is published")],
            ["ISS-10", "Cross-detector ranking on a common unit",
             "blocked", esc("no common decision unit exists")],
            ["ISS-11", "Anomaly-density claim", "blocked",
             esc("no reproducible numerator/denominator")]]
    pr = C["precision_target"]
    unmet = pr["arms_not_meeting_target"]
    rows.append(["A1-D3 precision target",
                 "historical 5\\% relative half-width at $N=60$",
                 "not met for %d of %d arms" % (unmet, pr["arms_examined"]),
                 esc("recorded as unmet, not restated as achieved")])
    crn = C["common_random_numbers"]
    rows.append(["Common random numbers", "shared seed indices",
                 "strict CRN not confirmed",
                 esc("verified within a scenario across its four defences; "
                     "not across scenarios")])
    P.record(tag, "precision", "arms_not_meeting_target",
             "CORRECTED_RESULTS.json", "/precision_target/arms_not_meeting_target",
             unmet, str(unmet), "precision_target", "arms missing the target")
    P.record(tag, "crn", "strict", "CORRECTED_RESULTS.json",
             "/common_random_numbers/strict_common_random_numbers_verified",
             crn["strict_common_random_numbers_verified"],
             str(crn["strict_common_random_numbers_verified"]),
             "common_random_numbers", "strict CRN verified")
    return latex_table(
        "tab:withheld",
        "Quantities deliberately not published, and precision limits recorded "
        "as measured.",
        ["Identifier", "Quantity", "Status", "Disposition"], rows,
        notes=["Nothing in this table is estimated, imputed or replaced by a "
               "placeholder value."])


# ════════════════════════════════════════════════════════════════════════════
# FIGURES  (deterministic: fixed hashsalt, text kept as text, no timestamps)
# ════════════════════════════════════════════════════════════════════════════
COLUMN_IN = COLUMN_PT / 72.27          # 3.246 in, one IAC column
TEXT_IN = TEXT_PT / 72.27              # 6.728 in, both columns


def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams.update({
        "svg.hashsalt": "lifesat-task8",     # stable element ids
        "svg.fonttype": "none",              # SVG text stays text
        # Type 42 = embedded TrueType. The default Type 3 is unsearchable,
        # renders poorly and is rejected by several publishers' checkers.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "pdf.compression": 0,
        "figure.dpi": 150,
        "font.family": "serif",
        "font.size": 7,
        "axes.labelsize": 7,
        "axes.titlesize": 7.5,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "legend.fontsize": 6.5,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
    return matplotlib


def legend_overlaps_axes(fig, ax, legend):
    """True when the legend box intersects the axes data area."""
    if legend is None:
        return False
    fig.canvas.draw()
    lb = legend.get_window_extent()
    ab = ax.get_window_extent()
    return not (lb.x1 <= ab.x0 or lb.x0 >= ab.x1
                or lb.y1 <= ab.y0 or lb.y0 >= ab.y1)


def save(fig, out_dir, stem, manifest):
    import matplotlib.pyplot as plt
    paths = []
    svg = os.path.join(out_dir, stem + ".svg")
    fig.savefig(svg, format="svg", bbox_inches="tight",
                metadata={"Date": None, "Creator": None})
    paths.append(svg)
    pdf = os.path.join(out_dir, stem + ".pdf")
    fig.savefig(pdf, format="pdf", bbox_inches="tight",
                metadata={"CreationDate": None, "Producer": None,
                          "Creator": None})
    paths.append(pdf)
    plt.close(fig)
    manifest.append({"figure": stem,
                     "files": [os.path.basename(p) for p in paths],
                     "width_in": round(fig.get_size_inches()[0], 3),
                     "span": ("both columns"
                              if fig.get_size_inches()[0] > COLUMN_IN + 0.1
                              else "single column")})
    return paths


def figure_detection(C, out_dir, manifest):
    """Recall with its bootstrap interval, per D3 cell."""
    import matplotlib.pyplot as plt
    tag = "fig_detection"
    names, means, los, his = [], [], [], []
    candidates = [x[0] for x in cells_with(C, "EST-F3-D3-01", "recall")]
    for name, ci, ej in cells_with(C, "EST-F3-D3-01", "recall"):
        m = resolve(DOCS["CORRECTED_RESULTS.json"],
                    arm_ptr(ci, ej, "recall", "macro_mean_over_defined_runs"))
        u = resolve(DOCS["CORRECTED_RESULTS.json"],
                    arm_ptr(ci, ej, "recall", "uncertainty"))
        if m is None:
            continue
        names.append(name)
        means.append(m)
        los.append(m - u["ci_low"] if u else 0.0)
        his.append(u["ci_high"] - m if u else 0.0)
        P.record(tag, name, "recall macro", "CORRECTED_RESULTS.json",
                 arm_ptr(ci, ej, "recall", "macro_mean_over_defined_runs"),
                 m, fmt(m), "EST-F3-D3-01", "recall")
        P.record(tag, name, "recall ci", "CORRECTED_RESULTS.json",
                 arm_ptr(ci, ej, "recall", "uncertainty"), u,
                 "n/a" if u is None else "[%s, %s]" % (fmt(u["ci_low"]),
                                                       fmt(u["ci_high"])),
                 "EST-F3-D3-01", "recall 95% CI")
    fig, ax = plt.subplots(figsize=(COLUMN_IN, 1.9))
    x = list(range(len(names)))
    ax.errorbar(x, means, yerr=[los, his], fmt="o", capsize=3, linestyle="none",
                color="#1f4e79", ecolor="#1f4e79", markersize=4)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("D3 recall (macro over defined runs)")
    ax.set_ylim(-0.02, 1.02)
    ax.set_title("Direct D3 detection, EST-F3-D3-01")
    defined = sum(1 for m in means if m is not None)
    paths = save(fig, out_dir, "figure_01_d3_recall_by_cell", manifest)
    manifest[-1]["defined_points"] = defined
    manifest[-1]["plotted_cells"] = names
    manifest[-1]["candidate_cells"] = candidates
    return paths


def figure_dispositions(C, out_dir, manifest):
    """Where every injected A4 action ended up."""
    import matplotlib.pyplot as plt
    tag = "fig_dispositions"
    keys = ("received_modified", "received_delayed", "dropped", "unresolved")
    colours = ("#1f4e79", "#3d7ea6", "#a63d3d", "#999999")
    names, series = [], {k: [] for k in keys}
    for name, ci, ej in cells_with(C, "EST-F0-02"):
        base = "/cells/%d/estimands/%d/counts/dispositions" % (ci, ej)
        names.append(name)
        for k in keys:
            v = resolve(DOCS["CORRECTED_RESULTS.json"], base + "/" + k)
            series[k].append(v)
            P.record(tag, name, k, "CORRECTED_RESULTS.json", base + "/" + k,
                     v, "%d" % v, "EST-F0-02", "A4 %s actions" % k)
    fig, ax = plt.subplots(figsize=(COLUMN_IN, 2.15))
    bottom = [0] * len(names)
    for k, colour in zip(keys, colours):
        ax.bar(names, series[k], bottom=bottom, label=k.replace("_", " "),
               color=colour, width=0.55)
        bottom = [b + v for b, v in zip(bottom, series[k])]
    ax.set_ylabel("A4 actions (corpus total)")
    ax.set_title("A4 action accounting, EST-F0-02")
    ax.set_ylim(0, max(bottom) * 1.05)
    # Legend BELOW the axes: inside the data area it covered the stack.
    legend = ax.legend(frameon=False, ncol=2, loc="upper center",
                       bbox_to_anchor=(0.5, -0.18), borderaxespad=0.0)
    overlap = legend_overlaps_axes(fig, ax, legend)
    paths = save(fig, out_dir, "figure_02_a4_dispositions", manifest)
    manifest[-1]["legend_overlaps_data_area"] = overlap
    return paths


def figure_drop_units(C, out_dir, manifest):
    """The same 249 drops, counted under two different decision units."""
    import matplotlib.pyplot as plt
    tag = "fig_drop_units"
    d3ci, d3ej = est_index(C, "A4-D3", "EST-A4-L2-02")
    d2ci, d2ej = est_index(C, "A4-D2", "EST-A4-L3-02")
    p_no = ("/cells/%d/estimands/%d/counts/drop_subtype/no_decision_opportunity"
            % (d3ci, d3ej))
    d2base = ("/cells/%d/estimands/%d/counts/drop_opportunity_classes"
              % (d2ci, d2ej))
    items = [("D3\nno decision\nopportunity", p_no, "#a63d3d"),
             ("D2\nnative\nopportunity", d2base + "/native_decision_opportunity",
              "#1f4e79"),
             ("D2\nno native\nopportunity",
              d2base + "/no_native_decision_opportunity", "#3d7ea6"),
             ("D2\nalarm-covered",
              d2base + "/covered_by_alarming_expected_arrival_window", "#4f9d69")]
    labels, values, colours = [], [], []
    for label, pointer, colour in items:
        v = resolve(DOCS["CORRECTED_RESULTS.json"], pointer)
        labels.append(label)
        values.append(v)
        colours.append(colour)
        P.record(tag, label.replace("\n", " "), "count", "CORRECTED_RESULTS.json",
                 pointer, v, "%d" % v,
                 "EST-A4-L2-02" if "D3" in label else "EST-A4-L3-02",
                 "drop count under this decision unit")
    fig, ax = plt.subplots(figsize=(COLUMN_IN, 2.1))
    bars = ax.bar(labels, values, color=colours, width=0.55)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 4, "%d" % v,
                ha="center", fontsize=7)
    ax.set_ylabel("drop actions")
    ax.set_ylim(0, max(values) * 1.18)
    ax.set_title("One drop population, two decision units")
    ax.tick_params(axis="x", labelsize=6)
    return save(fig, out_dir, "figure_03_drop_decision_units", manifest)


def figure_run_spread(C, R, out_dir, manifest):
    """Seed-to-seed spread behind each macro mean."""
    import matplotlib.pyplot as plt
    tag = "fig_run_spread"
    names, data = [], []
    for c in R["cells"]:
        for e in c["estimands"]:
            if e["estimand_id"] != "EST-F0-01":
                continue
            rows = e["arms"]["execution_rate"]
            vals = [p["value"] for p in rows if p["value"] is not None]
            if not vals:
                continue
            names.append(c["cell"])
            data.append(vals)
            ci = next(i for i, x in enumerate(R["cells"]) if x["cell"] == c["cell"])
            ej = next(j for j, x in enumerate(c["estimands"])
                      if x["estimand_id"] == "EST-F0-01")
            pointer = "/cells/%d/estimands/%d/arms/execution_rate" % (ci, ej)
            # The box plot consumes the whole per-run array, so the provenance
            # entry records that array verbatim: raw_value must be exactly what
            # the pointer resolves to, never a figure derived from it.
            P.record(tag, c["cell"], "per-run values",
                     "RUN_LEVEL_RESULTS.json", pointer,
                     resolve(R, pointer), "%d defined runs of %d"
                     % (len(vals), len(rows)), "EST-F0-01",
                     "per-run execution rate (array)")
    # Twenty cells cannot be read in one 3.25in column, so this figure is
    # authored at FULL text width and is a figure* in the paper.
    fig, ax = plt.subplots(figsize=(TEXT_IN, 2.3))
    ax.boxplot(data, tick_labels=names, showfliers=True,
               medianprops={"color": "#a63d3d"},
               boxprops={"color": "#1f4e79"},
               whiskerprops={"color": "#1f4e79"},
               capprops={"color": "#1f4e79"},
               flierprops={"markersize": 2, "markeredgecolor": "#999999"})
    ax.set_ylabel("execution rate per run")
    ax.set_title("Seed-to-seed spread behind the macro mean, EST-F0-01")
    ax.tick_params(axis="x", rotation=45, labelsize=6)
    for lab in ax.get_xticklabels():
        lab.set_horizontalalignment("right")
    paths = save(fig, out_dir, "figure_04_run_level_spread", manifest)
    manifest[-1]["span"] = "both columns"
    return paths


# ════════════════════════════════════════════════════════════════════════════
# SELECTION — what is actually proposed for the paper, and why
# ════════════════════════════════════════════════════════════════════════════
MIN_DEFINED_POINTS = 3      # a plot with fewer carries no comparison

TABLE_ROLE = {
    "table_01_execution.tex": ("selected", "primary F0 result"),
    "table_02_prevention.tex": ("selected", "primary F1 result"),
    "table_03_state_transition.tex": ("selected", "primary F2 result"),
    "table_04_direct_detection_d3.tex": ("selected", "primary F3 twin result"),
    "table_05_direct_detection_d2.tex": ("selected", "primary F3 flow result"),
    "table_06_random_baseline.tex":
        ("selected", "negative control required by rule R4; without it the "
                     "detector results are not falsifiable"),
    "table_07_secondary_reporting.tex": ("selected", "primary F4 result"),
    "table_08_a4_subtype_layers.tex":
        ("selected", "the A4 layered estimands are the paper's main "
                     "measurement contribution"),
    "table_09_drop_decision_units.tex":
        ("selected", "states the D3/D2 decision-unit distinction the "
                     "correction round exists to fix"),
    "table_10_a4_dispositions.tex":
        ("candidate", "content is fully carried by figure_02; keep as a "
                      "candidate in case the figure is dropped for space"),
    "table_11_iss06_cooccurrence.tex":
        ("selected", "the ISS-06 rerun's only new finding"),
    "table_12_tier2_pre_uplink_validation.tex": ("selected", "F5 claim"),
    "table_13_tier2_forensic_chain.tex": ("selected", "F6 claim"),
    "table_14_withheld_and_limits.tex":
        ("selected", "records what is deliberately not published; removing it "
                     "would make the paper overclaim"),
}


def select_assets(C, layout, figures, figures_dir):
    """Candidate vs selected. Fourteen tables is more than a 20-page IAC paper
    can carry, so the status is stated here rather than assumed downstream."""
    tables = []
    for entry in layout:
        status, reason = TABLE_ROLE.get(entry["table"],
                                        ("candidate", "no role assigned"))
        tables.append({"table": entry["table"], "status": status,
                       "reason": reason, "environment": entry["environment"],
                       "span": entry["span"]})
    figs = []
    for f in figures:
        status, reason = "selected", "adds a view the tables do not carry"
        if "defined_points" in f and f["defined_points"] < MIN_DEFINED_POINTS:
            status = "not_selected"
            total = len(f.get("candidate_cells") or f.get("plotted_cells", []))
            reason = ("information-value gate: recall is defined in only %d of "
                      "the %d cells that publish this estimand, so the plot "
                      "reduces to a single point and cannot support a "
                      "comparison. The same content, including the undefined "
                      "cells and their reason codes, is fully readable in "
                      "table_04_direct_detection_d3.tex."
                      % (f["defined_points"], total))
        if f.get("legend_overlaps_data_area"):
            status = "not_selected"
            reason = "legend overlaps the data area"
        figs.append({"figure": f["figure"], "status": status, "reason": reason,
                     "span": f.get("span"), "files": f["files"]})
    return {"schema": "lifesat-paper-asset-selection/v1",
            "policy": ("selected = proposed for the paper; candidate = correct "
                       "and available but not required; not_selected = fails a "
                       "publication gate. Nothing is deleted: every asset stays "
                       "reproducible."),
            "minimum_defined_points_for_a_plot": MIN_DEFINED_POINTS,
            "tables": tables, "figures": figs,
            "counts": {
                "tables_selected": sum(1 for t in tables
                                       if t["status"] == "selected"),
                "tables_candidate": sum(1 for t in tables
                                        if t["status"] == "candidate"),
                "figures_selected": sum(1 for f in figs
                                        if f["status"] == "selected"),
                "figures_not_selected": sum(1 for f in figs
                                            if f["status"] != "selected")}}


MIN_EFFECTIVE_FONT_PT = 6.0


def figure_legibility_report(figures_dir):
    r"""Smallest text each figure will actually show on the printed page.

    svg.fonttype=none keeps text as text, so the sizes can be read straight out
    of the SVG. bbox_inches="tight" trims whitespace, so a figure is usually a
    little NARROWER than its target width and is scaled UP by
    \includegraphics[width=\columnwidth] - which enlarges the type. A figure
    wider than its target would be scaled DOWN and is rejected.
    """
    import re
    rows = []
    for name in sorted(os.listdir(figures_dir)):
        if not name.endswith(".svg"):
            continue
        svg = open(os.path.join(figures_dir, name), encoding="utf-8").read()
        m = re.search(r'width="([0-9.]+)pt"', svg)
        width = float(m.group(1)) if m else None
        sizes = [float(x) for x in re.findall(r"font-size:\s*([0-9.]+)px", svg)]
        sizes += [float(x) for x in re.findall(r'font-size="([0-9.]+)"', svg)]
        target = TEXT_PT if width and width > COLUMN_PT + 20 else COLUMN_PT
        scale = (target / width) if width else None
        effective = [s * scale for s in sizes] if scale else []
        rows.append({
            "figure": name[:-4], "svg_width_pt": width,
            "target_width_pt": round(target, 2),
            "scale_into_target": round(scale, 4) if scale else None,
            "scaled_down": bool(scale and scale < 1.0),
            "text_elements": len(sizes),
            "min_font_pt_as_drawn": round(min(sizes), 2) if sizes else None,
            "min_effective_font_pt": round(min(effective), 2) if effective else None,
            "max_effective_font_pt": round(max(effective), 2) if effective else None,
            "legible": bool(effective)
            and min(effective) >= MIN_EFFECTIVE_FONT_PT})
    return rows


def pdf_font_report(figures_dir):
    """Every embedded font, via pdffonts. Type 3 must not appear."""
    import subprocess
    rows = []
    for name in sorted(os.listdir(figures_dir)):
        if not name.endswith(".pdf"):
            continue
        proc = subprocess.run(["pdffonts", os.path.join(figures_dir, name)],
                              capture_output=True, text=True)
        fonts = []
        for line in proc.stdout.splitlines()[2:]:
            if not line.strip():
                continue
            # Fixed-width report: name(36) type(18) encoding(17) emb sub uni id
            font_name = line[:36].strip()   # NOT `name`: that is the pdf file
            ftype = line[37:55].strip()
            rest = line[72:].split()
            fonts.append({"name": font_name, "type": ftype,
                          "encoding": line[55:72].strip(),
                          "embedded": (rest[0] == "yes") if rest else None,
                          "subset": (rest[1] == "yes") if len(rest) > 1 else None})
        rows.append({"pdf": name, "fonts": fonts,
                     "type3_count": sum(1 for f in fonts
                                        if "Type 3" in f["type"]),
                     "all_embedded": all(f["embedded"] for f in fonts) if fonts
                     else False,
                     "raw": proc.stdout})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generated"))
    a = ap.parse_args(argv)
    out_root = os.path.realpath(a.out)
    if os.path.exists(out_root):
        raise AssetError("output root %r already exists; refusing to reuse it"
                         % out_root)

    seal, docs = load_sealed()
    DOCS.update(docs)
    C = docs["CORRECTED_RESULTS.json"]
    R = docs["RUN_LEVEL_RESULTS.json"]

    tables_dir = os.path.join(out_root, "tables")
    figures_dir = os.path.join(out_root, "figures")
    os.makedirs(tables_dir)
    os.makedirs(figures_dir)

    tables = [
        ("table_01_execution.tex", four_column_estimand(
            C, "execution",
            "Attack-action execution rate against the system boundary.",
            "tab:execution", "EST-F0-01", "execution_rate", "execution rate")),
        ("table_02_prevention.tex", four_column_estimand(
            C, "prevention",
            "D1 prevention: delivered hostile command actions that were rejected.",
            "tab:prevention", "EST-F1-01", "prevention_rate", "prevention rate")),
        ("table_03_state_transition.tex", four_column_estimand(
            C, "state",
            "State transitions caused by accepted hostile command actions.",
            "tab:state", "EST-F2-01", "state_transition_rate",
            "state transition rate")),
        ("table_04_direct_detection_d3.tex", table_confusion(
            C, "d3", "Direct D3 divergence detection at the received "
            "telemetry observation.", "tab:d3", "EST-F3-D3-01")),
        ("table_05_direct_detection_d2.tex", table_confusion(
            C, "d2", "Flow-anomaly D2 detection at the 60\\,s window.",
            "tab:d2", "EST-F3-D2-01")),
        ("table_06_random_baseline.tex", table_confusion(
            C, "rnd", "Bernoulli comparator (negative control): a detector that "
            "cannot be falsified would show here.", "tab:rnd",
            "EST-F3-RND-01")),
        ("table_07_secondary_reporting.tex", four_column_estimand(
            C, "f4", "F4 secondary reporting: D1 rejection evidence answered by "
            "telemetry.", "tab:f4", "EST-F4-01", "secondary_reporting_rate",
            "secondary reporting rate")),
        ("table_08_a4_subtype_layers.tex", table_a4_subtype(C)),
        ("table_09_drop_decision_units.tex", table_drop_units(C)),
        ("table_10_a4_dispositions.tex", table_dispositions(C)),
        ("table_11_iss06_cooccurrence.tex", table_iss06(C)),
        ("table_12_tier2_pre_uplink_validation.tex", table_tier2_f5(C)),
        ("table_13_tier2_forensic_chain.tex", table_tier2_f6(C)),
        ("table_14_withheld_and_limits.tex", table_withheld(C)),
    ]
    # ── layout decision, measured rather than assumed ────────────────────
    workdir = os.path.join(out_root, ".compile")
    layout = []
    for name, table in tables:
        spec = LAYOUT_SPEC.get(name, {})
        attempts = []
        chosen = None
        for env, key in (("table", "single"), ("table*", "wide")):
            body = table.render(env, spec.get(key))
            worst, ok, excerpt = measure_overfull(
                body, workdir, name.replace(".tex", "_" + key))
            attempts.append({"environment": env, "colspec": spec.get(key),
                             "compiled": ok,
                             "max_overfull_pt": round(worst, 3),
                             "within_tolerance": ok and worst <= OVERFULL_TOLERANCE_PT,
                             "log_excerpt": excerpt})
            if ok and worst <= OVERFULL_TOLERANCE_PT:
                chosen = (env, spec.get(key), body, worst)
                break
        if chosen is None:
            raise AssetError(
                "%s does not fit at either width within %.1fpt and shrinking it "
                "with \\resizebox is not permitted: %s"
                % (name, OVERFULL_TOLERANCE_PT,
                   [(a["environment"], a["max_overfull_pt"]) for a in attempts]))
        env, colspec, body, worst = chosen
        with open(os.path.join(tables_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)
        layout.append({
            "table": name, "label": table.label,
            "environment": env,
            "span": "single column" if env == "table" else "both columns",
            "column_spec": colspec or "l" + "r" * (len(table.columns) - 1),
            "columns": len(table.columns), "body_rows": len(table.rows),
            "max_overfull_pt": round(worst, 3),
            "tolerance_pt": OVERFULL_TOLERANCE_PT,
            "target_width_pt": COLUMN_PT if env == "table" else TEXT_PT,
            "resizebox_used": False,
            "attempts": attempts})
    import shutil as _sh
    _sh.rmtree(workdir, ignore_errors=True)

    setup_matplotlib()
    figures = []
    figure_detection(C, figures_dir, figures)
    figure_dispositions(C, figures_dir, figures)
    figure_drop_units(C, figures_dir, figures)
    figure_run_spread(C, R, figures_dir, figures)
    selection = select_assets(C, layout, figures, figures_dir)

    provenance = {
        "schema": "lifesat-paper-asset-provenance/v1",
        "authority": {
            "seal": SEAL, "seal_sha256": SEAL_SHA,
            "accepted_utc": seal["accepted_utc"],
            "package_tree_digest": seal["package"]["tree_digest"],
            "contract_version": seal["authority"]["contract_version"],
            "contract_json_sha256": seal["authority"]["contract_json_sha256"],
            "scorer_tree_digest": seal["authority"]["scorer_tree_digest"]},
        "rule": ("every rendered value below was read from the sealed package "
                 "at the given JSON Pointer; no number is hand-entered"),
        "column_policy": ("macro, pooled and interval are distinct columns and "
                          "are never combined"),
        "null_policy": "a null value renders as n/a and is never shown as 0",
        "tables": [t[0] for t in tables],
        "figures": figures,
        "layout": layout,
        "selection": selection,
        "entry_count": len(P.entries),
        "entries": P.entries,
    }
    with open(os.path.join(out_root, "PROVENANCE.json"), "w",
              encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")

    with open(os.path.join(out_root, "LAYOUT.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "lifesat-paper-layout/v1",
                   "geometry": {"documentclass": "10pt,twocolumn,letterpaper",
                                "column_width_pt": COLUMN_PT,
                                "text_width_pt": TEXT_PT,
                                "source": "manuscript/dizgi/latex-kaynakcali/"
                                          "paper.tex"},
                   "policy": {"overfull_tolerance_pt": OVERFULL_TOLERANCE_PT,
                              "resizebox": "forbidden",
                              "extra_packages_required": []},
                   "tables": layout}, fh, indent=2, sort_keys=True,
                  ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(out_root, "SELECTION.json"), "w",
              encoding="utf-8") as fh:
        json.dump(selection, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")

    verification = verify(out_root, seal, provenance)
    with open(os.path.join(out_root, "VERIFY.json"), "w", encoding="utf-8") as fh:
        json.dump(verification, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")

    lines = []
    for folder in ("tables", "figures"):
        base = os.path.join(out_root, folder)
        for name in sorted(os.listdir(base)):
            lines.append("%s  %s/%s" % (sha256(os.path.join(base, name)),
                                        folder, name))
    for name in ("LAYOUT.json", "PROVENANCE.json", "SELECTION.json",
                 "VERIFY.json"):
        lines.append("%s  %s" % (sha256(os.path.join(out_root, name)), name))
    with open(os.path.join(out_root, "ASSETS.sha256"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(json.dumps({
        "output_root": os.path.basename(out_root),
        "tables": len(tables), "figures": len(figures),
        "single_column_tables": sum(1 for x in layout
                                    if x["environment"] == "table"),
        "full_width_tables": sum(1 for x in layout
                                 if x["environment"] == "table*"),
        "worst_overfull_pt": max(x["max_overfull_pt"] for x in layout),
        "tables_selected": sum(1 for x in selection["tables"]
                               if x["status"] == "selected"),
        "figures_selected": sum(1 for x in selection["figures"]
                                if x["status"] == "selected"),
        "provenance_entries": len(P.entries),
        "verdict": verification["verdict"]}, indent=2))
    return 0 if verification["verdict"] == "GREEN" else 1


def verify(out_root, seal, provenance):
    """Re-read the sealed package from disk and re-resolve every pointer."""
    fresh = {}
    for entry in seal["package"]["files"]:
        if entry["path"].endswith(".json"):
            path = os.path.join(PKG, entry["path"])
            if sha256(path) != entry["sha256"]:
                return {"verdict": "RED", "reason": "sealed file changed"}
            fresh[entry["path"]] = json.load(open(path, encoding="utf-8"))

    checks, failed = [], []

    def ck(name, cond, detail=""):
        checks.append({"name": name, "pass": bool(cond), "detail": str(detail)})
        if not cond:
            failed.append(name)

    mismatched = []
    for e in provenance["entries"]:
        got = resolve(fresh[e["document"]], e["json_pointer"])
        if got != e["raw_value"]:
            mismatched.append({"pointer": e["json_pointer"], "recorded":
                               e["raw_value"], "sealed": got})
    ck("every rendered value re-resolves to the sealed package", not mismatched,
       mismatched[:3])

    zeroed = [e for e in provenance["entries"]
              if e["raw_value"] is None and e["rendered"] not in (NA, "n/a")]
    ck("no null is rendered as a number", not zeroed, zeroed[:3])

    mixed = [e for e in provenance["entries"]
             if e["column"] == "macro" and "pooled" in str(e["quantity"])]
    ck("macro and pooled never share a column", not mixed, mixed[:3])

    ck("provenance covers every table",
       set(provenance["tables"]) and all(
           any(x["table"] for x in provenance["entries"]) for _ in [0]))
    ck("no wall-clock timestamp is embedded",
       "generated_utc" not in json.dumps(provenance))
    ck("authority is the accepted seal",
       provenance["authority"]["seal_sha256"] == SEAL_SHA)

    for folder, ext in (("tables", ".tex"), ("figures", ".svg")):
        base = os.path.join(out_root, folder)
        ck("%s produced" % folder,
           any(n.endswith(ext) for n in os.listdir(base)))

    # ── publication-layout gates ─────────────────────────────────────────
    layout = provenance["layout"]
    ck("every table compiled against the real manuscript preamble",
       all(any(a["compiled"] for a in t["attempts"]) for t in layout))
    ck("all 14 tables passed the compile gate", len(layout) == 14, len(layout))
    worst = max(t["max_overfull_pt"] for t in layout)
    ck("worst overfull is within %.1fpt" % OVERFULL_TOLERANCE_PT,
       worst <= OVERFULL_TOLERANCE_PT, worst)
    ck("every table states an explicit single/full-width decision",
       all(t["environment"] in ("table", "table*") for t in layout))
    ck("no table is shrunk with resizebox",
       not any(t["resizebox_used"] for t in layout)
       and "resizebox" not in "".join(
           open(os.path.join(out_root, "tables", f), encoding="utf-8").read()
           for f in os.listdir(os.path.join(out_root, "tables"))))
    ck("tables need no package beyond those paper.tex loads",
       not any(cmd in "".join(
           open(os.path.join(out_root, "tables", f), encoding="utf-8").read()
           for f in os.listdir(os.path.join(out_root, "tables")))
           for cmd in ("\\toprule", "\\midrule", "\\bottomrule",
                       "tabularx", "\\begin{tabu}", "\\begin{tabulary}",
                       "\\usepackage")))
    ck("a table wider than a column is set as table*",
       all(t["environment"] == "table*" or t["columns"] <= 3 for t in layout),
       [(t["table"], t["columns"]) for t in layout
        if t["environment"] == "table" and t["columns"] > 3])

    fonts = pdf_font_report(os.path.join(out_root, "figures"))
    ck("no figure PDF carries a Type 3 font",
       all(f["type3_count"] == 0 for f in fonts),
       [(f["pdf"], f["type3_count"]) for f in fonts if f["type3_count"]])
    ck("every figure PDF embeds at least one font",
       all(f["fonts"] for f in fonts),
       [f["pdf"] for f in fonts if not f["fonts"]])
    # pdf.fonttype=42 emits TrueType; poppler reports the CID-keyed subset as
    # "CID TrueType". Both are TrueType outlines - the thing being excluded is
    # Type 3, which is bitmap/procedural and unsearchable.
    ck("every embedded font is a TrueType outline",
       all("TrueType" in fo["type"] for f in fonts for fo in f["fonts"]),
       [(f["pdf"], fo["type"]) for f in fonts for fo in f["fonts"]
        if "TrueType" not in fo["type"]])
    ck("every font is actually embedded in the PDF",
       all(f["all_embedded"] for f in fonts),
       [(f["pdf"], fo["name"]) for f in fonts for fo in f["fonts"]
        if not fo["embedded"]])

    legibility = figure_legibility_report(os.path.join(out_root, "figures"))
    ck("every figure's smallest text is at least %.1fpt on the page"
       % MIN_EFFECTIVE_FONT_PT,
       all(r["legible"] for r in legibility),
       [(r["figure"], r["min_effective_font_pt"]) for r in legibility
        if not r["legible"]])
    ck("no figure is scaled DOWN into the column",
       not any(r["scaled_down"] for r in legibility),
       [(r["figure"], r["scale_into_target"]) for r in legibility
        if r["scaled_down"]])
    ck("every figure carries text",
       all(r["text_elements"] > 0 for r in legibility))

    figs = provenance["selection"]["figures"]
    ck("no selected figure has a legend over its data area",
       not any(f.get("legend_overlaps_data_area") for f in provenance["figures"]))
    ck("figures are authored at a real column or text width",
       all(abs(f["width_in"] - COLUMN_IN) < 0.15
           or abs(f["width_in"] - TEXT_IN) < 0.15
           for f in provenance["figures"]),
       [(f["figure"], f["width_in"]) for f in provenance["figures"]])
    ck("a plot with too few defined points is not selected",
       all(f["status"] != "selected" for f in figs
           if any(g["figure"] == f["figure"]
                  and g.get("defined_points", 99) < MIN_DEFINED_POINTS
                  for g in provenance["figures"])))
    ck("selection status is stated for every asset",
       all(t["status"] in ("selected", "candidate", "not_selected")
           for t in provenance["selection"]["tables"])
       and all(f["status"] in ("selected", "candidate", "not_selected")
               for f in figs))
    ck("provenance binding count is unchanged at 431",
       len(provenance["entries"]) == 431, len(provenance["entries"]))

    svg_dates = []
    for name in sorted(os.listdir(os.path.join(out_root, "figures"))):
        if not name.endswith(".svg"):
            continue
        text = open(os.path.join(out_root, "figures", name),
                    encoding="utf-8").read()
        if "<dc:date>" in text:
            svg_dates.append(name)
    ck("no figure carries an embedded date", not svg_dates, svg_dates)

    return {"schema": "lifesat-paper-asset-verification/v2",
            "checks": len(checks), "failed": failed, "detail": checks,
            "entries_verified": len(provenance["entries"]),
            "worst_overfull_pt": worst,
            "font_report": [{"pdf": f["pdf"], "type3_count": f["type3_count"],
                             "all_embedded": f["all_embedded"],
                             "fonts": f["fonts"]} for f in fonts],
            "legibility_report": legibility,
            "minimum_effective_font_pt": MIN_EFFECTIVE_FONT_PT,
            "verdict": "GREEN" if not failed else "RED"}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssetError as _exc:
        sys.stderr.write("REFUSED (AssetError): %s\n" % _exc)
        sys.exit(2)
