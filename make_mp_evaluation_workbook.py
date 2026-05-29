import argparse
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from mp_api.client import MPRester

from phase_evaluator import DEFAULT_RESULT_DIR, ROOT, load_dotenv


def extract_mp_id(cif_name):
    match = re.search(r"(mp-\d+)", str(cif_name))
    return match.group(1) if match else ""


def classify_mp_stability(e_above_hull):
    if pd.isna(e_above_hull):
        return "mp_unknown"
    e_above_hull = float(e_above_hull)
    if e_above_hull <= 0.001:
        return "stable_single"
    if e_above_hull <= 0.03:
        return "low_metastable"
    if e_above_hull <= 0.10:
        return "high_metastable"
    return "unstable_multi_risk"


def fetch_mp_summary_map(material_ids, api_key, chunk_size=500):
    summary_map = {}
    with MPRester(api_key, mute_progress_bars=True) as mpr:
        for start in range(0, len(material_ids), chunk_size):
            chunk = material_ids[start : start + chunk_size]
            docs = mpr.materials.summary.search(
                material_ids=chunk,
                fields=[
                    "material_id",
                    "formula_pretty",
                    "energy_above_hull",
                    "is_stable",
                    "is_metal",
                    "chemsys",
                    "symmetry",
                ],
                num_chunks=None,
                chunk_size=chunk_size,
            )
            for doc in docs:
                material_id = str(doc.material_id)
                symmetry = getattr(doc, "symmetry", None)
                mp_space_group = ""
                if symmetry is not None:
                    mp_space_group = getattr(symmetry, "symbol", "") or ""
                summary_map[material_id] = {
                    "MP_formula": doc.formula_pretty,
                    "MP_energy_above_hull_eV_per_atom": doc.energy_above_hull,
                    "MP_is_stable": doc.is_stable,
                    "MP_is_metal": doc.is_metal,
                    "MP_chemsys": doc.chemsys,
                    "MP_space_group": mp_space_group,
                    "MP_stability_class": classify_mp_stability(doc.energy_above_hull),
                }
    return summary_map


def safe_sheet_name(name):
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name)
    return cleaned[:31] or "sheet"


def autosize_columns(writer, sheet_name, df):
    worksheet = writer.sheets[sheet_name]
    for idx, column in enumerate(df.columns, start=1):
        series = df[column].astype(str)
        width = max([len(str(column)), *(series.head(200).map(len).tolist())]) + 2
        worksheet.column_dimensions[worksheet.cell(row=1, column=idx).column_letter].width = min(width, 60)


def write_workbook(df, output_path):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="MP 평가 전체", index=False)
        autosize_columns(writer, "MP 평가 전체", df)

        for prediction, group in df.groupby("예측결과(멀티인지 싱글인지)", dropna=False):
            sheet_name = safe_sheet_name(str(prediction))
            group.to_excel(writer, sheet_name=sheet_name, index=False)
            autosize_columns(writer, sheet_name, group)

        for stability_class, group in df.groupby("MP_stability_class", dropna=False):
            sheet_name = safe_sheet_name(f"MP_{stability_class}")
            group.to_excel(writer, sheet_name=sheet_name, index=False)
            autosize_columns(writer, sheet_name, group)


def parse_args():
    parser = argparse.ArgumentParser(description="Add MP evaluation columns and split results into workbook sheets.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RESULT_DIR / "phase_result_mp_alloys_20260513_144654.csv",
    )
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    return parser.parse_args()


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("MP_API_KEY")
    if not api_key:
        raise RuntimeError("MP_API_KEY is missing. Add it to .env.")

    args = parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    result_dir = args.result_dir if args.result_dir.is_absolute() else ROOT / args.result_dir
    result_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_path, encoding="utf-8-sig")
    df.insert(1, "MP_material_id", df["cif파일 제목"].map(extract_mp_id))

    material_ids = sorted(set(item for item in df["MP_material_id"].tolist() if item))
    print(f"Fetching MP summaries for {len(material_ids)} material ids...")
    summary_map = fetch_mp_summary_map(material_ids, api_key)

    summary_df = pd.DataFrame.from_dict(summary_map, orient="index")
    summary_df.index.name = "MP_material_id"
    summary_df = summary_df.reset_index()

    merged = df.merge(summary_df, on="MP_material_id", how="left")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_xlsx = result_dir / f"phase_result_mp_alloys_with_MP_eval_{timestamp}.xlsx"
    output_csv = result_dir / f"phase_result_mp_alloys_with_MP_eval_{timestamp}.csv"

    merged.to_csv(output_csv, index=False, encoding="utf-8-sig")
    write_workbook(merged, output_xlsx)

    print(f"Rows: {len(merged)}")
    print("MP stability counts:")
    print(merged["MP_stability_class"].value_counts(dropna=False).to_string())
    print(f"Workbook written to {output_xlsx}")
    print(f"Flat CSV written to {output_csv}")


if __name__ == "__main__":
    main()
