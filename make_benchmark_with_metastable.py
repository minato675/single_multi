import argparse
import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

from phase_evaluator import DEFAULT_RESULT_DIR, ROOT


THRESHOLDS = [0.01, 0.02, 0.03, 0.04, 0.05]


def safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def f1(precision, recall):
    return safe_div(2 * precision * recall, precision + recall)


def fmt(value):
    return f"{float(value):.6f}"


def pred_label_from_score(single_score, threshold):
    # single_score = exp(-E_hull / default_threshold). Recovering E_hull is
    # unnecessary here because the workbook lacks model E_hull by default.
    # Use the current result label for the 0.03 calibrated threshold summary.
    raise NotImplementedError


def binary_label_from_mp_class(mp_class):
    if mp_class == "stable_single":
        return "single"
    if mp_class == "unstable_multi_risk":
        return "multi"
    return None


def binary_label_from_prediction(prediction):
    if prediction == "멀티 가능성 높음":
        return "multi"
    if prediction in ["싱글 후보", "싱글(다른 결정구조 가능)"]:
        return "single"
    return None


def compute_binary_metrics(df):
    rows = []
    for _, row in df.iterrows():
        true_label = binary_label_from_mp_class(row["MP_stability_class"])
        pred_label = binary_label_from_prediction(row["예측결과(멀티인지 싱글인지)"])
        if true_label and pred_label:
            rows.append((true_label, pred_label))

    tp_single = sum(true == "single" and pred == "single" for true, pred in rows)
    fn_single = sum(true == "single" and pred == "multi" for true, pred in rows)
    fp_single = sum(true == "multi" and pred == "single" for true, pred in rows)
    tn_single = sum(true == "multi" and pred == "multi" for true, pred in rows)

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

    return {
        "summary_type": "strict_binary_excluding_metastable",
        "description": "MP stable_single vs MP unstable_multi_risk only; metastable classes excluded from binary metrics.",
        "total_evaluated": total,
        "accuracy": fmt(accuracy),
        "balanced_accuracy": fmt(balanced_accuracy),
        "single_precision": fmt(single_precision),
        "single_recall": fmt(single_recall),
        "single_f1": fmt(single_f1),
        "multi_precision": fmt(multi_precision),
        "multi_recall": fmt(multi_recall),
        "multi_f1": fmt(multi_f1),
        "tp_single": tp_single,
        "fn_single": fn_single,
        "fp_single": fp_single,
        "tn_single": tn_single,
    }


def stability_counts(df):
    rows = []
    counts = df["MP_stability_class"].value_counts(dropna=False).to_dict()
    for cls in ["stable_single", "low_metastable", "high_metastable", "unstable_multi_risk"]:
        rows.append(
            {
                "MP_stability_class": cls,
                "count": int(counts.get(cls, 0)),
                "ratio": fmt(safe_div(counts.get(cls, 0), len(df))),
            }
        )
    return rows


def crosstab_rows(df):
    table = pd.crosstab(
        df["MP_stability_class"],
        df["예측결과(멀티인지 싱글인지)"],
        dropna=False,
    )
    rows = []
    for mp_class, values in table.iterrows():
        total = int(values.sum())
        row = {"MP_stability_class": mp_class, "total": total}
        for column in table.columns:
            count = int(values[column])
            row[str(column)] = count
            row[f"{column}_ratio"] = fmt(safe_div(count, total))
        rows.append(row)
    return rows


def write_csv(path, rows):
    if not rows:
        return
    columns = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_workbook(path, metric_row, counts_rows, cross_rows):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([metric_row]).to_excel(writer, sheet_name="엄격 binary 지표", index=False)
        pd.DataFrame(counts_rows).to_excel(writer, sheet_name="MP 안정성 구간 개수", index=False)
        pd.DataFrame(cross_rows).to_excel(writer, sheet_name="MP구간별 예측분포", index=False)


def parse_args():
    parser = argparse.ArgumentParser(description="Create benchmark summary including MP metastable classes.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RESULT_DIR / "phase_result_mp_alloys_with_MP_eval_20260513_145518.csv",
    )
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    result_dir = args.result_dir if args.result_dir.is_absolute() else ROOT / args.result_dir
    result_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_path, encoding="utf-8-sig")
    metric_row = compute_binary_metrics(df)
    counts_rows = stability_counts(df)
    cross_rows = crosstab_rows(df)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    metrics_csv = result_dir / f"benchmark_with_metastable_metrics_{timestamp}.csv"
    counts_csv = result_dir / f"benchmark_with_metastable_counts_{timestamp}.csv"
    cross_csv = result_dir / f"benchmark_with_metastable_crosstab_{timestamp}.csv"
    workbook = result_dir / f"benchmark_with_metastable_{timestamp}.xlsx"

    write_csv(metrics_csv, [metric_row])
    write_csv(counts_csv, counts_rows)
    write_csv(cross_csv, cross_rows)
    write_workbook(workbook, metric_row, counts_rows, cross_rows)

    print(f"Metrics CSV written to {metrics_csv}")
    print(f"Counts CSV written to {counts_csv}")
    print(f"Crosstab CSV written to {cross_csv}")
    print(f"Workbook written to {workbook}")
    print(metric_row)


if __name__ == "__main__":
    main()
