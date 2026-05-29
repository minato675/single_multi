import argparse
import os
import re
from pathlib import Path

from mp_api.client import MPRester
from pymatgen.io.cif import CifWriter

from phase_evaluator import DEFAULT_INPUT_DIR, ROOT, load_dotenv


def safe_name(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def fetch_structure(material_id, api_key):
    with MPRester(api_key) as mpr:
        return mpr.get_structure_by_material_id(material_id)


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch a Materials Project structure as CIF.")
    parser.add_argument(
        "--material-id",
        default="mp-149",
        help="Materials Project material id. Default: mp-149 (Si).",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_INPUT_DIR)
    return parser.parse_args()


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("MP_API_KEY")
    if not api_key:
        raise RuntimeError("MP_API_KEY is missing. Add it to .env.")

    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    structure = fetch_structure(args.material_id, api_key)
    formula = safe_name(structure.composition.reduced_formula)
    output_path = output_dir / f"{args.material_id}_{formula}.cif"
    CifWriter(structure).write_file(output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
