import argparse
import itertools
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from mp_api.client import MPRester
from pymatgen.analysis.phase_diagram import PhaseDiagram

from phase_evaluator import (
    ALL_COLUMNS,
    DEFAULT_RESULT_DIR,
    ROOT,
    build_chgnet_phase_entries,
    calibration_domain_features,
    classify_competition,
    decomposition_structures_to_text,
    decomposition_to_text,
    format_float,
    get_mp_entries,
    get_space_group,
    laves_entropy_features,
    literature_evidence,
    load_chgnet_model,
    load_dotenv,
    min_interatomic_distance,
    prediction_with_competition,
    raw_ehull_risk,
    score_from_e_above_hull,
    screening_prediction,
    write_csv,
    write_excel,
)


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


def is_target_doc(doc, element_pool):
    elements = doc_elements(doc)
    if len(elements) < 2:
        return False
    if not elements.issubset(METALLIC_ELEMENTS):
        return False
    return elements.issubset(element_pool)


def fetch_mp_docs(api_key, target_count, max_docs, chunk_size, num_chunks, element_pool, fallback_general):
    fields = [
        "material_id",
        "formula_pretty",
        "chemsys",
        "energy_above_hull",
        "is_stable",
        "is_metal",
        "elements",
    ]
    docs = []
    seen = set()
    chemsys_list = []
    sorted_pool = sorted(element_pool)
    for size in range(2, min(len(sorted_pool), 6) + 1):
        for combo in itertools.combinations(sorted_pool, size):
            chemsys_list.append("-".join(combo))

    with MPRester(api_key, mute_progress_bars=True) as mpr:
        for chemsys in chemsys_list:
            if len(docs) >= target_count:
                break
            fetched = mpr.materials.summary.search(
                chemsys=chemsys,
                is_metal=True,
                fields=fields,
                num_chunks=num_chunks,
                chunk_size=chunk_size,
            )
            for doc in fetched:
                material_id = str(doc.material_id)
                if material_id in seen:
                    continue
                if is_target_doc(doc, element_pool):
                    docs.append(doc)
                    seen.add(material_id)
                if len(docs) >= target_count or len(docs) >= max_docs:
                    break
        if fallback_general and len(docs) < target_count:
            for num_elements in [2, 3, 4, 5]:
                if len(docs) >= target_count or len(docs) >= max_docs:
                    break
                fetched = mpr.materials.summary.search(
                    is_metal=True,
                    num_elements=num_elements,
                    fields=fields,
                    num_chunks=num_chunks,
                    chunk_size=chunk_size,
                )
                for doc in fetched:
                    material_id = str(doc.material_id)
                    if material_id in seen:
                        continue
                    elements = doc_elements(doc)
                    if len(elements) >= 2 and elements.issubset(METALLIC_ELEMENTS):
                        docs.append(doc)
                        seen.add(material_id)
                    if len(docs) >= target_count or len(docs) >= max_docs:
                        break
    return docs


def group_by_chemsys(docs):
    grouped = defaultdict(list)
    for doc in docs:
        grouped[doc.chemsys].append(doc)
    return grouped


def evaluate_mp_entry(
    entry,
    decomposition,
    raw_e_hull,
    args,
    material_id,
    mp_doc,
):
    structure = entry.structure
    composition = entry.composition
    elements = sorted([el.symbol for el in composition.elements])
    min_dist = min_interatomic_distance(structure)
    entropy = laves_entropy_features(composition, args.entropy_temperature, args.entropy_weight)
    corrected_e_hull = max(0.0, raw_e_hull - entropy["weighted_entropy_stabilization_eV_per_atom"])
    competition_type = classify_competition(composition, decomposition)
    single_score, multi_score, _ = score_from_e_above_hull(raw_e_hull, args.single_threshold)
    corrected_single_score, _, _ = score_from_e_above_hull(corrected_e_hull, args.single_threshold)
    literature_match, literature_basis = literature_evidence(f"{material_id}_{composition.reduced_formula}.cif")
    calibration_domain, calibration_basis = calibration_domain_features(entropy, elements)

    row = {column: "" for column in ALL_COLUMNS}
    row["cif파일 제목"] = f"{material_id}_{composition.reduced_formula}.cif"
    row["화학식"] = composition.reduced_formula
    row["결정구조"] = get_space_group(structure)
    row["단상 점수"] = format_float(single_score)
    row["다상 점수"] = format_float(multi_score)
    row["보정 단상 점수"] = format_float(corrected_single_score)
    row["예측결과(신조성 룰)"] = screening_prediction(
        raw_e_hull,
        corrected_e_hull,
        args.single_threshold,
        args.metastable_threshold,
        entropy["laves_AB2_like"],
    )
    row["예측결과(raw hull)"] = prediction_with_competition(raw_e_hull, args.single_threshold, competition_type)
    row["raw_Ehull_위험도"] = raw_ehull_risk(raw_e_hull)
    row["경쟁 유형"] = competition_type
    row["예상되는 멀티 phase 조성들"] = decomposition_to_text(decomposition)
    row["예상 phase 결정구조들"] = decomposition_structures_to_text(decomposition)
    row["raw_energy_above_hull_eV_per_atom"] = format_float(raw_e_hull)
    row["config_entropy_kB_per_atom"] = format_float(entropy["config_entropy_kB_per_atom"])
    row["entropy_temperature_K"] = format_float(args.entropy_temperature, 1)
    row["entropy_stabilization_eV_per_atom"] = format_float(entropy["entropy_stabilization_eV_per_atom"])
    row["entropy_weight"] = format_float(args.entropy_weight, 3)
    row["entropy_corrected_e_hull_eV_per_atom"] = format_float(corrected_e_hull)
    row["single_threshold_eV_per_atom"] = format_float(args.single_threshold)
    row["metastable_threshold_eV_per_atom"] = format_float(args.metastable_threshold)
    row["A_site_elements"] = entropy["A_site_elements"]
    row["B_site_elements"] = entropy["B_site_elements"]
    row["B_to_A_ratio"] = format_float(entropy["B_to_A_ratio"], 4)
    row["laves_AB2_like"] = "TRUE" if entropy["laves_AB2_like"] else "FALSE"
    row["calibration_domain"] = calibration_domain
    row["calibration_basis"] = calibration_basis
    row["literature_match"] = literature_match
    row["literature_basis"] = literature_basis
    row["chgnet_energy_eV_per_atom"] = format_float(entry.energy_per_atom)
    row["hull_energy_source"] = "CHGNet-only hull from MP structures"
    row["space_group"] = row["결정구조"]
    row["min_distance_A"] = format_float(min_dist, 4)
    row["num_sites"] = str(len(structure))
    row["chemical_system"] = "-".join(elements)
    row["상태"] = "성공"
    row["메시지"] = (
        f"MP_material_id={material_id}; "
        f"MP_formula={getattr(mp_doc, 'formula_pretty', '')}; "
        f"MP_Ehull={format_float(getattr(mp_doc, 'energy_above_hull', None))}; "
        f"MP_is_stable={getattr(mp_doc, 'is_stable', '')}"
    )
    return row


def evaluate_docs(args, api_key, docs):
    grouped = group_by_chemsys(docs)
    chgnet_model = load_chgnet_model()
    rows = []
    skipped = 0

    sorted_groups = sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)
    for idx, (chemsys, chemsys_docs) in enumerate(sorted_groups, start=1):
        if len(rows) >= args.target_count:
            break
        elements = chemsys.split("-")
        try:
            mp_entries = get_mp_entries(elements, api_key)
            chgnet_entries = build_chgnet_phase_entries(chgnet_model, mp_entries)
            if len(chgnet_entries) < len(elements):
                skipped += len(chemsys_docs)
                continue
            phase_diagram = PhaseDiagram(chgnet_entries)
            chgnet_by_id = {str(entry.entry_id).replace("-GGA", ""): entry for entry in chgnet_entries}
        except Exception as exc:
            print(f"[skip] {chemsys}: {exc}")
            skipped += len(chemsys_docs)
            continue

        print(f"[{idx}/{len(grouped)}] {chemsys}: requested={len(chemsys_docs)}, total_rows={len(rows)}")
        for doc in chemsys_docs:
            if len(rows) >= args.target_count:
                break
            material_id = str(doc.material_id)
            entry = chgnet_by_id.get(material_id)
            if entry is None:
                skipped += 1
                continue
            try:
                decomposition, raw_e_hull = phase_diagram.get_decomp_and_e_above_hull(entry)
                rows.append(evaluate_mp_entry(entry, decomposition, raw_e_hull, args, material_id, doc))
            except Exception as exc:
                skipped += 1
                print(f"[skip] {material_id}: {exc}")

    return rows, skipped, len(grouped)


def parse_args():
    parser = argparse.ArgumentParser(description="Screen MP alloy structures with the new-composition rules.")
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--max-docs", type=int, default=10000)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--num-chunks", type=int, default=10)
    parser.add_argument("--element-pool", default="Ti,Zr,Nb,Mn,Cr,Fe")
    parser.add_argument("--no-fallback-general", action="store_true")
    parser.add_argument("--single-threshold", type=float, default=0.03)
    parser.add_argument("--metastable-threshold", type=float, default=0.08)
    parser.add_argument("--entropy-temperature", type=float, default=1000.0)
    parser.add_argument("--entropy-weight", type=float, default=1.0)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    return parser.parse_args()


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("MP_API_KEY")
    if not api_key:
        raise RuntimeError("MP_API_KEY is missing. Add it to .env.")

    args = parse_args()
    result_dir = args.result_dir if args.result_dir.is_absolute() else ROOT / args.result_dir
    element_pool = {item.strip() for item in args.element_pool.split(",") if item.strip()}

    print(f"Fetching MP metallic docs in element pool: {', '.join(sorted(element_pool))}")
    docs = fetch_mp_docs(
        api_key,
        args.target_count,
        args.max_docs,
        args.chunk_size,
        args.num_chunks,
        element_pool,
        not args.no_fallback_general,
    )
    print(f"Fetched target docs: {len(docs)}")

    rows, skipped, grouped_count = evaluate_docs(args, api_key, docs)
    csv_path = write_csv(rows, result_dir)
    xlsx_path = write_excel(rows, result_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = result_dir / f"mp_new_rule_screen_summary_{timestamp}.txt"
    summary_path.write_text(
        "\n".join(
            [
                f"target_count={args.target_count}",
                f"fetched_docs={len(docs)}",
                f"evaluated_rows={len(rows)}",
                f"skipped={skipped}",
                f"grouped_chemical_systems={grouped_count}",
                f"element_pool={','.join(sorted(element_pool))}",
                f"csv={csv_path}",
                f"xlsx={xlsx_path}",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Evaluated rows: {len(rows)}")
    print(f"Skipped rows: {skipped}")
    print(f"Result CSV: {csv_path}")
    print(f"Result Excel: {xlsx_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
