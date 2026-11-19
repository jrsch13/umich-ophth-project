# OpenPose posture-analysis scripts

These scripts convert the supplied research notebooks into reusable command-line
analysis code.

## Suggested project location

```text
station-service/
└── analysis/
    ├── __init__.py
    ├── openpose_io.py
    ├── posture_metrics.py
    ├── analyze_openpose.py
    └── evaluate_protocol.py
```

## Dependencies

```powershell
pip install numpy pandas matplotlib
```

## Production-style analysis

Side-view OpenPose JSON:

```powershell
python .\station-service\analysis\analyze_openpose.py `
  --json-dir ".\station-service\sessions\<SESSION>\openpose\side\json" `
  --timestamps-csv ".\station-service\sessions\<SESSION>\raw\side_timestamps.csv" `
  --view side `
  --neutral-seconds 10 `
  --output-dir ".\station-service\sessions\<SESSION>\analysis\side"
```

Rear/rear-oblique OpenPose JSON:

```powershell
python .\station-service\analysis\analyze_openpose.py `
  --json-dir ".\station-service\sessions\<SESSION>\openpose\rear\json" `
  --timestamps-csv ".\station-service\sessions\<SESSION>\raw\rear_timestamps.csv" `
  --view rear `
  --neutral-seconds 10 `
  --output-dir ".\station-service\sessions\<SESSION>\analysis\rear"
```

If no timestamp CSV is supplied, time is computed from `frame / --fps`
(default 30 FPS).

## Outputs

Each analysis directory contains:

```text
posture_metrics.csv
confidence_summary.csv
summary.json
plots/
```

For `--view side`, the script computes:

- trunk flexion/extension
- neck flexion/extension relative to trunk

For `--view rear`, the script computes:

- trunk lateral lean
- right/left shoulder hiking normalized by trunk length

`--view all` computes every notebook metric and is mainly useful for reproducing
the original notebook experiments.

## Thresholds copied from the notebook

- shoulder hiking: 0.01 normalized trunk-length ratio
- neck flexion/extension: 5 degrees
- trunk lateral lean: 5 degrees
- trunk flexion/extension: 5 degrees

These are research/development thresholds from the supplied notebook, not
validated clinical cutoffs.

## Neutral baseline

The supplied notebooks use the first 10 seconds as a neutral baseline. The CLI
keeps that behavior by default:

```text
--neutral-seconds 10
```

For the resident interface, the eventual integration should ideally use the
known neutral-reference interval stored in session metadata rather than assuming
every session's first 10 seconds are neutral.

## Confidence handling

OpenPose points with confidence 0 or coordinates (0, 0) are treated as missing.
You can additionally mask low-confidence points:

```text
--min-confidence 0.5
```

The default is 0.0 so the scripts remain close to the notebook calculations.

## Experimental protocol evaluator

`evaluate_protocol.py` preserves the notebook's validation-only protocol where
each posture condition lasts 10 seconds in a fixed order.

Example:

```powershell
python .\station-service\analysis\evaluate_protocol.py `
  --metrics-csv ".\station-service\sessions\<SESSION>\analysis\all\posture_metrics.csv" `
  --output-dir ".\station-service\sessions\<SESSION>\analysis\protocol"
```

Do not use that hard-coded condition schedule for normal resident sessions.
