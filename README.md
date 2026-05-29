# High-Entropy Laves Phase Screener

CHGNet and Materials Project based screening tools for single-phase tendency in metallic alloys, with an entropy-corrected rule set for high-entropy C14 AB2 Laves candidates.

The original 0 K convex-hull rule is intentionally kept as a diagnostic signal, but the main screening label uses an additional configurational-entropy correction for new-composition discovery.

## What This Repository Does

```text
CIF or MP structure
-> CHGNet energy prediction
-> CHGNet-only phase diagram from MP competing phases
-> raw energy above hull
-> C14 AB2-like sublattice entropy correction
-> new-composition screening label
-> CSV/XLSX report with evidence columns
```

This is a screening pipeline, not a final proof of synthesizability. Use promising candidates for follow-up DFT relaxation, SQS/configurational sampling, CALPHAD/thermodynamic checks, and experiments.

## Main Scripts

| File | Purpose |
| --- | --- |
| `phase_evaluator.py` | Evaluate local CIF files in `input_cif.dir` and write CSV/XLSX reports. |
| `screen_mp_new_rules.py` | Fetch metallic structures from Materials Project and screen them with the new-composition rules. |
| `fetch_mp_cif.py` | Download one MP structure as a CIF. |
| `benchmark_mp_classifier.py` | Benchmark raw CHGNet hull classification for a selected chemical system. |
| `benchmark_mp_alloys_large.py` | Older MP alloy benchmark workflow. |
| `make_mp_evaluation_workbook.py` | Add MP stability metadata to a phase-result workbook. |

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set your Materials Project API key:

```env
MP_API_KEY=your_materials_project_api_key_here
```

Never commit `.env`. It is ignored by `.gitignore`.

## Evaluate Local CIF Files

Put ordered CIF files into `input_cif.dir`, then run:

```powershell
.\.venv\Scripts\python.exe phase_evaluator.py
```

Useful options:

```powershell
.\.venv\Scripts\python.exe phase_evaluator.py --input .\input_cif.dir\example.cif
.\.venv\Scripts\python.exe phase_evaluator.py --single-threshold 0.03 --metastable-threshold 0.08
.\.venv\Scripts\python.exe phase_evaluator.py --entropy-temperature 1000 --entropy-weight 1.0
```

Outputs are written to `result.dir` as CSV and XLSX. The workbook contains:

- `항목 설명`: column definitions
- `phase_result`: screening results and evidence values
- `문헌 근거`: calibration notes used while developing the rule set

## Screen MP Candidates

Default run:

```powershell
.\.venv\Scripts\python.exe screen_mp_new_rules.py --target-count 1000
```

By default, the script first searches the Ti/Zr/Nb/Mn/Cr/Fe pool and then fills the remaining count with broader metallic MP alloys. To restrict to only the element pool:

```powershell
.\.venv\Scripts\python.exe screen_mp_new_rules.py --target-count 1000 --no-fallback-general
```

Change the element pool:

```powershell
.\.venv\Scripts\python.exe screen_mp_new_rules.py --element-pool Ti,Zr,Nb,Mn,Cr,Fe,V
```

## Screening Labels

The new-composition rule does not use direct literature matching for the final label.

```text
raw_e_hull <= 0.03 eV/atom
=> 단상 후보

laves_AB2_like and entropy_corrected_e_hull <= 0.03 eV/atom
=> 엔트로피 보정 단상 후보

laves_AB2_like and 0.03 < entropy_corrected_e_hull <= 0.08 eV/atom
=> 고온 단상 가능 후보

laves_AB2_like and 0.08 < entropy_corrected_e_hull <= 0.12 eV/atom
=> 준안정 Laves 후보(계산상 위험 높음)

otherwise
=> 멀티 위험 후보
```

Always inspect these evidence columns:

- `raw_energy_above_hull_eV_per_atom`
- `config_entropy_kB_per_atom`
- `entropy_stabilization_eV_per_atom`
- `entropy_corrected_e_hull_eV_per_atom`
- `raw_Ehull_위험도`
- `calibration_domain`
- `calibration_basis`
- `예상되는 멀티 phase 조성들`

## Calibration Domain

The entropy correction was designed around Ti/Zr-based C14 AB2 Laves alloy chemistry, especially A-site elements such as Ti/Zr/Nb and B-site elements such as Mn/Cr/Fe. Candidates outside that domain can still be evaluated, but the corrected label should be treated as weaker evidence.

## Repository Hygiene

Ignored by default:

- `.env`
- `.venv`
- `input_cif.dir/*`
- `result.dir/*`
- `*.pdf`, `*.csv`, `*.xlsx`

Keep only small examples or documentation under version control. Generated reports and local CIF batches should stay out of Git unless there is a deliberate reason to publish them.
