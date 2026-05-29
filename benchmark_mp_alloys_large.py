import argparse
import csv
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from mp_api.client import MPRester
from pymatgen.analysis.phase_diagram import PhaseDiagram

from benchmark_mp_classifier import (
    METRIC_COLUMNS,
    compute_metrics,
    label_from_mp_hull,
    predict_from_chgnet_hull,
    write_metrics_csv,
)
from phase_evaluator import (
    DEFAULT_RESULT_DIR,
    REQUIRED_COLUMNS,
    ROOT,
    build_chgnet_phase_entries,
    classify_competition,
    decomposition_structures_to_text,
    decomposition_to_text,
    format_float,
    get_mp_entries,
    load_chgnet_model,
    load_dotenv,
    prediction_with_competition,
    score_from_e_above_hull,
)
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


METALLIC_ELEMENTS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn",
    "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo",
    "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba", "La", "Ce",
    "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb",
    "Bi",
}


def doc_elements(doc):
    return {str(element) for element in doc.elements}


def is_alloy_doc(doc):
    elements = doc_elements(doc)
    return len(elements) >= 2 and elements.issubset(METALLIC_ELEMENTS)


def fetch_alloy_docs(api_key, chunk_size, num_chunks, max_docs):
    fields = [
        "material_id",
        "formula_pretty",
        "chemsys",
        "energy_above_hull",
        "is_metal",
        "elements",
    ]
    docs = []
    with MPRester(api_key, mute_progress_bars=True) as mpr:
        for num_elements in [2, 3, 4]:
            if len(docs) >= max_docs:
                break
            fetched = mpr.materials.summary.search(
                is_metal=True,
                num_elements=num_elements,
                fields=fields,
                num_chunks=num_chunks,
                chunk_size=chunk_size,
            )
            for doc in fetched:
                if is_alloy_doc(doc):
                    docs.append(doc)
                if len(docs) >= max_docs:
                    break
    return docs


def group_docs_by_chemsys(docs):
    grouped = defaultdict(list)
    for doc in docs:
        grouped[doc.chemsys].append(doc)
    return grouped


def write_phase_result_csv(rows, result_dir):
    result_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = result_dir / f"phase_result_mp_alloys_{timestamp}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in REQUIRED_COLUMNS})
    return output_path


def structure_info(structure):
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
        return analyzer.get_space_group_symbol(), str(analyzer.get_crystal_system())
    except Exception:
        return "", ""


def build_phase_and_benchmark_rows(args, api_key, chgnet_model, grouped_docs):
    phase_rows = []
    benchmark_base_rows = []
    processed_systems = 0
    skipped_systems = 0

    sorted_groups = sorted(grouped_docs.items(), key=lambda item: len(item[1]), reverse=True)
    for chemsys, docs in sorted_groups:
        if len(phase_rows) >= args.target_count:
            break
        if args.max_chemsys and processed_systems >= args.max_chemsys:
            break

        elements = chemsys.split("-")
        try:
            mp_entries = get_mp_entries(elements, api_key)
            chgnet_entries = build_chgnet_phase_entries(chgnet_model, mp_entries)
            if len(chgnet_entries) < len(elements):
                skipped_systems += 1
                continue
            chgnet_phase_diagram = PhaseDiagram(chgnet_entries)
            chgnet_entry_by_id = {str(entry.entry_id): entry for entry in chgnet_entries}
        except Exception:
            skipped_systems += 1
            continue

        mp_phase_diagram = PhaseDiagram(mp_entries)
        mp_entry_by_id = {str(entry.entry_id): entry for entry in mp_entries}
        selected_chgnet_entries = [
            entry
            for entry in chgnet_entries
            if len(entry.composition.elements) >= 2
            and {el.symbol for el in entry.composition.elements}.issubset(METALLIC_ELEMENTS)
        ]
        selected_chgnet_entries = sorted(
            selected_chgnet_entries,
            key=lambda entry: entry.composition.reduced_formula,
        )
        processed_systems += 1
        print(
            f"[{processed_systems}] {chemsys}: entries={len(selected_chgnet_entries)}, "
            f"current_total={len(phase_rows)}"
        )

        for chgnet_entry in selected_chgnet_entries:
            if len(phase_rows) >= args.target_count:
                break
            material_id = str(chgnet_entry.entry_id)

            try:
                decomposition, chgnet_e_above_hull = chgnet_phase_diagram.get_decomp_and_e_above_hull(
                    chgnet_entry
                )
            except Exception:
                continue

            competition_type = classify_competition(chgnet_entry.composition, decomposition)
            single_score, multi_score, _ = score_from_e_above_hull(
                chgnet_e_above_hull,
                args.single_threshold,
            )
            prediction_kr = prediction_with_competition(
                chgnet_e_above_hull,
                args.single_threshold,
                competition_type,
            )
            space_group, _ = structure_info(chgnet_entry.structure)

            phase_rows.append(
                {
                    "cif파일 제목": f"{material_id}.cif",
                    "화학식": chgnet_entry.composition.reduced_formula,
                    "결정구조": space_group,
                    "단상 점수": format_float(single_score),
                    "다상 점수": format_float(multi_score),
                    "예측결과(멀티인지 싱글인지)": prediction_kr,
                    "경쟁 유형": competition_type,
                    "예상되는 멀티 phase 조성들": decomposition_to_text(decomposition),
                    "예상 phase 결정구조들": decomposition_structures_to_text(decomposition),
                }
            )

            mp_entry = mp_entry_by_id.get(material_id)
            if mp_entry is not None:
                _, mp_e_above_hull = mp_phase_diagram.get_decomp_and_e_above_hull(mp_entry)
                true_label = label_from_mp_hull(
                    mp_e_above_hull,
                    args.mp_single_threshold,
                    args.mp_multi_threshold,
                )
            else:
                true_label = None

            if true_label is not None:
                benchmark_base_rows.append(
                    {
                        "chemical_system": chemsys,
                        "material_id": material_id,
                        "formula": chgnet_entry.composition.reduced_formula,
                        "true_label": true_label,
                        "mp_e_above_hull": format_float(mp_e_above_hull),
                        "chgnet_e_above_hull": format_float(chgnet_e_above_hull),
                        "chgnet_e_above_hull_raw": chgnet_e_above_hull,
                    }
                )

    return phase_rows, benchmark_base_rows, processed_systems, skipped_systems


def compute_sweep_metrics(base_rows, args):
    thresholds = [float(item.strip()) for item in args.sweep_thresholds.split(",") if item.strip()]
    metric_rows = []
    for threshold in thresholds:
        rows = []
        for row in base_rows:
            benchmark_row = row.copy()
            benchmark_row["pred_label"] = predict_from_chgnet_hull(
                row["chgnet_e_above_hull_raw"],
                threshold,
            )
            rows.append(benchmark_row)
        metric_rows.append(
            compute_metrics(
                rows,
                args,
                threshold,
                f"alloy_large_single_threshold={threshold}",
                "mp_alloy_large",
            )
        )
    return metric_rows


def parse_args():
    parser = argparse.ArgumentParser(description="Large MP alloy benchmark and phase-result export.")
    parser.add_argument("--target-count", type=int, default=5000)
    parser.add_argument("--max-docs", type=int, default=20000)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--num-chunks", type=int, default=8)
    parser.add_argument("--max-chemsys", type=int, default=None)
    parser.add_argument("--single-threshold", type=float, default=0.03)
    parser.add_argument("--sweep-thresholds", default="0.01,0.02,0.03,0.04,0.05")
    parser.add_argument("--mp-single-threshold", type=float, default=0.001)
    parser.add_argument("--mp-multi-threshold", type=float, default=0.10)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    return parser.parse_args()


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("MP_API_KEY")
    if not api_key:
        raise RuntimeError("MP_API_KEY is missing. Add it to .env.")

    args = parse_args()
    result_dir = args.result_dir if args.result_dir.is_absolute() else ROOT / args.result_dir

    print("Fetching metallic alloy summaries from MP...")
    docs = fetch_alloy_docs(api_key, args.chunk_size, args.num_chunks, args.max_docs)
    print(f"Fetched alloy-like docs: {len(docs)}")
    grouped_docs = group_docs_by_chemsys(docs)
    print(f"Grouped chemical systems: {len(grouped_docs)}")

    chgnet_model = load_chgnet_model()
    phase_rows, benchmark_rows, processed_systems, skipped_systems = build_phase_and_benchmark_rows(
        args,
        api_key,
        chgnet_model,
        grouped_docs,
    )

    phase_path = write_phase_result_csv(phase_rows, result_dir)
    metric_rows = compute_sweep_metrics(benchmark_rows, args)
    metrics_path = write_metrics_csv(metric_rows, result_dir)

    print("\nLarge alloy benchmark complete")
    print(f"phase_rows: {len(phase_rows)}")
    print(f"benchmark_labeled_rows: {len(benchmark_rows)}")
    print(f"processed_systems: {processed_systems}")
    print(f"skipped_systems: {skipped_systems}")
    print(f"phase_result CSV: {phase_path}")
    print(f"benchmark metrics CSV: {metrics_path}")

    for row in metric_rows:
        print(
            "threshold={threshold}: accuracy={accuracy}, balanced_accuracy={balanced}, "
            "single_precision={sp}, single_recall={sr}, multi_recall={mr}".format(
                threshold=row["single_threshold_eV_per_atom"],
                accuracy=row["accuracy"],
                balanced=row["balanced_accuracy"],
                sp=row["single_precision"],
                sr=row["single_recall"],
                mr=row["multi_recall"],
            )
        )


if __name__ == "__main__":
    main()
