import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

from pymatgen.analysis.phase_diagram import PhaseDiagram

from phase_evaluator import (
    DEFAULT_RESULT_DIR,
    ROOT,
    build_chgnet_phase_entries,
    get_mp_entries,
    load_chgnet_model,
    load_dotenv,
)


METRIC_COLUMNS = [
    "chemical_system",
    "change",
    "true_single_count",
    "true_multi_count",
    "total_evaluated",
    "accuracy",
    "balanced_accuracy",
    "single_precision",
    "single_recall",
    "single_f1",
    "multi_precision",
    "multi_recall",
    "multi_f1",
    "tp_single",
    "fn_single",
    "fp_single",
    "tn_single",
    "single_threshold_eV_per_atom",
    "mp_single_label_threshold_eV_per_atom",
    "mp_multi_label_threshold_eV_per_atom",
]


def safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def f1(precision, recall):
    return safe_div(2 * precision * recall, precision + recall)


def format_float(value):
    return f"{float(value):.6f}"


def label_from_mp_hull(e_above_hull, stable_threshold, multi_threshold):
    if e_above_hull <= stable_threshold:
        return "single"
    if e_above_hull >= multi_threshold:
        return "multi"
    return None


def predict_from_chgnet_hull(e_above_hull, single_threshold):
    return "single" if e_above_hull <= single_threshold else "multi"


def select_entries(labeled_rows, max_per_class):
    singles = [row for row in labeled_rows if row["true_label"] == "single"]
    multis = [row for row in labeled_rows if row["true_label"] == "multi"]

    singles = sorted(singles, key=lambda row: row["mp_e_above_hull"])[:max_per_class]
    multis = sorted(multis, key=lambda row: row["mp_e_above_hull"], reverse=True)[:max_per_class]
    return singles + multis


def compute_metrics(rows, args, single_threshold, change, chemical_system):
    tp_single = sum(row["true_label"] == "single" and row["pred_label"] == "single" for row in rows)
    fn_single = sum(row["true_label"] == "single" and row["pred_label"] == "multi" for row in rows)
    fp_single = sum(row["true_label"] == "multi" and row["pred_label"] == "single" for row in rows)
    tn_single = sum(row["true_label"] == "multi" and row["pred_label"] == "multi" for row in rows)

    single_precision = safe_div(tp_single, tp_single + fp_single)
    single_recall = safe_div(tp_single, tp_single + fn_single)
    single_f1 = f1(single_precision, single_recall)

    tp_multi = tn_single
    fp_multi = fn_single
    fn_multi = fp_single
    multi_precision = safe_div(tp_multi, tp_multi + fp_multi)
    multi_recall = safe_div(tp_multi, tp_multi + fn_multi)
    multi_f1 = f1(multi_precision, multi_recall)

    total = len(rows)
    accuracy = safe_div(tp_single + tn_single, total)
    balanced_accuracy = (single_recall + multi_recall) / 2

    true_single_count = sum(row["true_label"] == "single" for row in rows)
    true_multi_count = sum(row["true_label"] == "multi" for row in rows)

    return {
        "chemical_system": chemical_system,
        "change": change,
        "true_single_count": true_single_count,
        "true_multi_count": true_multi_count,
        "total_evaluated": total,
        "accuracy": format_float(accuracy),
        "balanced_accuracy": format_float(balanced_accuracy),
        "single_precision": format_float(single_precision),
        "single_recall": format_float(single_recall),
        "single_f1": format_float(single_f1),
        "multi_precision": format_float(multi_precision),
        "multi_recall": format_float(multi_recall),
        "multi_f1": format_float(multi_f1),
        "tp_single": tp_single,
        "fn_single": fn_single,
        "fp_single": fp_single,
        "tn_single": tn_single,
        "single_threshold_eV_per_atom": single_threshold,
        "mp_single_label_threshold_eV_per_atom": args.mp_single_threshold,
        "mp_multi_label_threshold_eV_per_atom": args.mp_multi_threshold,
    }


def write_metrics_csv(metric_rows, result_dir):
    result_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = result_dir / f"benchmark_metrics_{timestamp}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=METRIC_COLUMNS)
        writer.writeheader()
        writer.writerows(metric_rows)
    return output_path


def write_predictions_csv(rows, result_dir):
    result_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = result_dir / f"benchmark_predictions_{timestamp}.csv"
    columns = [
        "material_id",
        "formula",
        "true_label",
        "pred_label",
        "mp_e_above_hull",
        "chgnet_e_above_hull",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row[column] for column in columns})
    return output_path


def parse_thresholds(text):
    return [float(item.strip()) for item in text.split(",") if item.strip()]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark CHGNet-only single/multi phase classification against MP hull labels."
    )
    parser.add_argument("--chemsys", default="Al-Ti-V", help="Chemical system, e.g. Al-Ti-V.")
    parser.add_argument(
        "--chemsys-list",
        default=None,
        help="Comma-separated chemical systems. Example: Al-Ti-V,Ti-Mn,Fe-O",
    )
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument("--max-per-class", type=int, default=30)
    parser.add_argument("--max-total", type=int, default=None)
    parser.add_argument("--single-threshold", type=float, default=0.03)
    parser.add_argument(
        "--sweep-thresholds",
        default=None,
        help="Comma-separated eV/atom thresholds, e.g. 0.01,0.02,0.03,0.04,0.05.",
    )
    parser.add_argument("--mp-single-threshold", type=float, default=0.001)
    parser.add_argument("--mp-multi-threshold", type=float, default=0.10)
    parser.add_argument("--save-predictions", action="store_true")
    return parser.parse_args()


def build_base_rows_for_chemsys(args, chemsys, api_key, chgnet_model):
    elements = [item.strip() for item in chemsys.split("-") if item.strip()]
    print(f"Fetching MP entries for {chemsys}...")
    mp_entries = get_mp_entries(elements, api_key)
    mp_phase_diagram = PhaseDiagram(mp_entries)

    labeled_rows = []
    for entry in mp_entries:
        structure = getattr(entry, "structure", None)
        if structure is None:
            continue
        _, mp_e_above_hull = mp_phase_diagram.get_decomp_and_e_above_hull(entry)
        true_label = label_from_mp_hull(
            mp_e_above_hull,
            args.mp_single_threshold,
            args.mp_multi_threshold,
        )
        if true_label is None:
            continue
        labeled_rows.append(
            {
                "entry": entry,
                "material_id": str(getattr(entry, "entry_id", "")),
                "formula": entry.composition.reduced_formula,
                "true_label": true_label,
                "mp_e_above_hull": mp_e_above_hull,
            }
        )

    selected_rows = select_entries(labeled_rows, args.max_per_class)
    if not selected_rows:
        print(f"No benchmark entries selected for {chemsys}.")
        return []

    print(f"Selected {len(selected_rows)} benchmark entries for {chemsys}.")
    chgnet_entries = build_chgnet_phase_entries(chgnet_model, mp_entries)
    chgnet_phase_diagram = PhaseDiagram(chgnet_entries)
    chgnet_entry_by_id = {str(entry.entry_id): entry for entry in chgnet_entries}

    base_rows = []
    for row in selected_rows:
        chgnet_entry = chgnet_entry_by_id.get(row["material_id"])
        if chgnet_entry is None:
            continue
        _, chgnet_e_above_hull = chgnet_phase_diagram.get_decomp_and_e_above_hull(chgnet_entry)
        base_rows.append(
            {
                "chemical_system": chemsys,
                "material_id": row["material_id"],
                "formula": row["formula"],
                "true_label": row["true_label"],
                "mp_e_above_hull": format_float(row["mp_e_above_hull"]),
                "chgnet_e_above_hull": format_float(chgnet_e_above_hull),
                "chgnet_e_above_hull_raw": chgnet_e_above_hull,
            }
        )
    return base_rows


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("MP_API_KEY")
    if not api_key:
        raise RuntimeError("MP_API_KEY is missing. Add it to .env.")

    args = parse_args()
    result_dir = args.result_dir if args.result_dir.is_absolute() else ROOT / args.result_dir

    if args.chemsys_list:
        chemsys_list = [item.strip() for item in args.chemsys_list.split(",") if item.strip()]
    else:
        chemsys_list = [args.chemsys]

    chgnet_model = load_chgnet_model()
    base_rows = []
    for chemsys in chemsys_list:
        base_rows.extend(build_base_rows_for_chemsys(args, chemsys, api_key, chgnet_model))

    if args.max_total is not None:
        singles = [row for row in base_rows if row["true_label"] == "single"]
        multis = [row for row in base_rows if row["true_label"] == "multi"]
        half = args.max_total // 2
        base_rows = singles[:half] + multis[: args.max_total - half]

    if not base_rows:
        print("No benchmark entries selected. Try lowering --mp-multi-threshold.")
        return

    print(f"Total selected benchmark entries: {len(base_rows)}")

    thresholds = parse_thresholds(args.sweep_thresholds) if args.sweep_thresholds else [args.single_threshold]
    metric_rows = []
    prediction_rows_for_selected_threshold = []
    for threshold in thresholds:
        benchmark_rows = []
        for row in base_rows:
            benchmark_row = row.copy()
            benchmark_row["pred_label"] = predict_from_chgnet_hull(
                row["chgnet_e_above_hull_raw"],
                threshold,
            )
            benchmark_rows.append(benchmark_row)

        metric_rows.append(
            compute_metrics(
                benchmark_rows,
                args,
                threshold,
                f"single_threshold={threshold}",
                "multi_system" if len(chemsys_list) > 1 else chemsys_list[0],
            )
        )
        if threshold == args.single_threshold:
            prediction_rows_for_selected_threshold = benchmark_rows

    metrics_path = write_metrics_csv(metric_rows, result_dir)

    print("\nBenchmark metrics")
    for metrics in metric_rows:
        print(
            "threshold={threshold}: accuracy={accuracy}, balanced_accuracy={balanced}, "
            "single_precision={sp}, single_recall={sr}, multi_recall={mr}".format(
                threshold=metrics["single_threshold_eV_per_atom"],
                accuracy=metrics["accuracy"],
                balanced=metrics["balanced_accuracy"],
                sp=metrics["single_precision"],
                sr=metrics["single_recall"],
                mr=metrics["multi_recall"],
            )
        )
    print(f"\nMetrics CSV written to {metrics_path}")

    if args.save_predictions:
        predictions_path = write_predictions_csv(prediction_rows_for_selected_threshold, result_dir)
        print(f"Predictions CSV written to {predictions_path}")


if __name__ == "__main__":
    main()
