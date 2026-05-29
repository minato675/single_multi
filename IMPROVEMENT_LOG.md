# 모델 개선 기록

날짜: 2026-05-13

## 기준

- 평가 대상 chemical system: `Al-Ti-V`
- MP 실제 라벨:
  - `MP energy above hull <= 0.001 eV/atom`: 실제 single
  - `MP energy above hull >= 0.10 eV/atom`: 실제 multi
  - 중간 영역은 benchmark에서 제외
- 모델 예측:
  - MP competing phase 구조들을 CHGNet으로 다시 계산
  - `CHGNet-only hull`에서 후보의 energy above hull 계산
  - threshold 이하이면 single, 초과이면 multi

## 1차 개선: single threshold sweep

변경 내용:

- 기존 기본 기준 `0.05 eV/atom`이 multi 구조를 single로 많이 보는 경향이 있어 threshold sweep을 수행했습니다.
- 비교 threshold:
  - `0.01`
  - `0.02`
  - `0.03`
  - `0.04`
  - `0.05`

결과 파일:

- `result.dir/benchmark_metrics_20260513_142204.csv`

| threshold | accuracy | balanced accuracy | single precision | single recall | multi recall |
|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.866667 | 0.825000 | 0.875000 | 0.700000 | 0.950000 |
| 0.02 | 0.900000 | 0.900000 | 0.818182 | 0.900000 | 0.900000 |
| 0.03 | 0.900000 | 0.900000 | 0.818182 | 0.900000 | 0.900000 |
| 0.04 | 0.933333 | 0.950000 | 0.833333 | 1.000000 | 0.900000 |
| 0.05 | 0.766667 | 0.825000 | 0.588235 | 1.000000 | 0.650000 |

해석:

- 기존 `0.05`는 single recall은 높지만 multi recall이 낮아, multi를 single로 과하게 추천했습니다.
- `0.04`는 single recall을 유지하면서 multi recall을 크게 개선했습니다.
- 현재 benchmark에서는 `0.04 eV/atom`이 가장 균형이 좋습니다.

적용:

- `phase_evaluator.py` 기본 `--single-threshold`를 `0.05`에서 `0.04`로 변경했습니다.
- `benchmark_mp_classifier.py` 기본 `--single-threshold`도 `0.04`로 변경했습니다.

주의:

- 이 threshold는 우선 `Al-Ti-V` benchmark에서 보정한 값입니다.
- 다른 chemical system, 특히 `Ti-Mn-X` 계에서는 별도 sweep이 필요할 수 있습니다.

## 2차 검증: 여러 MP chemical system 약 100개 benchmark

사용한 chemical system:

- `Al-Ti-V`
- `Ti-Mn`
- `Fe-O`
- `Ti-O`
- `Al-O`
- `Ni-Ti`
- `Co-Ni`
- `Mn-O`
- `Si-O`
- `Li-Fe-O`

변경 내용:

- 한 chemical system만 쓰면 threshold가 특정 계에 과적합될 수 있어, 여러 MP chemical system에서 총 100개 benchmark 데이터를 모았습니다.
- 일부 MP 구조는 CHGNet graph 생성이 실패할 수 있어, 해당 구조는 건너뛰고 benchmark가 계속 진행되도록 수정했습니다.

결과 파일:

- `result.dir/benchmark_metrics_20260513_142639.csv`

| threshold | accuracy | balanced accuracy | single precision | single recall | multi recall |
|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.890000 | 0.890000 | 1.000000 | 0.780000 | 1.000000 |
| 0.02 | 0.920000 | 0.920000 | 1.000000 | 0.840000 | 1.000000 |
| 0.03 | 0.930000 | 0.930000 | 0.977778 | 0.880000 | 0.980000 |
| 0.04 | 0.980000 | 0.980000 | 0.980000 | 0.980000 | 0.980000 |
| 0.05 | 0.960000 | 0.960000 | 0.925926 | 1.000000 | 0.920000 |

해석:

- 여러 chemical system에서 봐도 `0.04 eV/atom`이 가장 균형이 좋았습니다.
- `0.01`과 `0.02`는 multi를 잘 거르지만 실제 single을 놓치는 경향이 있습니다.
- `0.05`는 실제 single을 잘 잡지만 multi를 single로 보는 경향이 다시 커집니다.
- 현재 1차 screening 기본값으로는 `0.04 eV/atom`을 유지하는 것이 타당합니다.

현재 기본 설정:

- `phase_evaluator.py`: `--single-threshold 0.04`
- `benchmark_mp_classifier.py`: `--single-threshold 0.04`

## 3차 검증: MP alloy 5000개 phase result 및 대형 benchmark

요청에 따라 MP에 있는 합금계 위주로 5000개 phase result를 생성했습니다.

결과 파일:

- `result.dir/phase_result_mp_alloys_20260513_144654.csv`
- `result.dir/benchmark_metrics_20260513_144654.csv`

규모:

- phase result 행 수: `5000`
- benchmark 라벨이 명확한 행 수: `2522`
- 실제 single: `1472`
- 실제 multi: `1050`

threshold sweep 결과:

| threshold | accuracy | balanced accuracy | single precision | single recall | multi precision | multi recall |
|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.963521 | 0.967521 | 0.993562 | 0.943614 | 0.926157 | 0.991429 |
| 0.02 | 0.979778 | 0.980356 | 0.988316 | 0.976902 | 0.968135 | 0.983810 |
| 0.03 | 0.984140 | 0.982454 | 0.980537 | 0.992527 | 0.989341 | 0.972381 |
| 0.04 | 0.977399 | 0.973813 | 0.966997 | 0.995245 | 0.993049 | 0.952381 |
| 0.05 | 0.968279 | 0.962314 | 0.950194 | 0.997962 | 0.996926 | 0.926667 |

해석:

- 5000개 alloy 중심 benchmark에서는 `0.03 eV/atom`이 accuracy와 balanced accuracy 기준으로 가장 좋았습니다.
- `0.04`는 single recall은 조금 더 높지만 multi recall이 떨어져 multi를 single로 더 많이 놓칩니다.
- 합금계 후보 screening 기본값은 `0.03 eV/atom`이 더 타당합니다.

적용:

- `phase_evaluator.py` 기본 `--single-threshold`를 `0.03`으로 변경했습니다.
- `benchmark_mp_classifier.py` 기본 `--single-threshold`를 `0.03`으로 변경했습니다.
- `benchmark_mp_alloys_large.py` 기본 `--single-threshold`를 `0.03`으로 변경했습니다.
