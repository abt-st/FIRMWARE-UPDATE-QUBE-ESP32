#!/usr/bin/env python3
"""
analyze_sweep.py — Analizador y auditor de sweeps de swing-up

Reemplaza autoresearch.sh con análisis Python puro (funciona en Windows).
Reconstruye clasificaciones desde datos crudos — NO confía en la clasificación del sweep.

Uso:
  uv run python analyze_sweep.py [data_dir]
  uv run python analyze_sweep.py experiments/2026-06-15_sweep_v3/data
"""

import csv
import sys
from pathlib import Path


def find_latest_sweep(data_dir: Path) -> Path:
    """Find the most recent sweep directory."""
    sweeps = sorted(data_dir.glob("sweep_*"), reverse=True)
    if not sweeps:
        print(f"ERROR: No sweep directories in {data_dir}", file=sys.stderr)
        sys.exit(1)
    return sweeps[0]


def load_sweep(csv_path: Path) -> dict[tuple[int, int], dict]:
    """Load and group CSV data by (sp, attempt)."""
    attempts: dict[tuple[int, int], dict] = {}

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sp = int(row["sp"])
            attempt = int(row["attempt"])
            t = float(row["t"])
            pend = float(row["pend_deg"])
            mode = int(row["mode"])

            key = (sp, attempt)
            if key not in attempts:
                attempts[key] = {
                    "sp": sp,
                    "attempt": attempt,
                    "rows": 0,
                    "modes_seen": set(),
                    "mode_changes": [],
                    "t0": t,
                    "t_max": t,
                    "pend_min": pend,
                    "pend_max": pend,
                    "prev_mode": mode,
                    "lqr_entries": [],
                    "lqr_losses": 0,
                    "lqr_loss_times": [],
                    "in_lqr": False,
                }

            a = attempts[key]
            a["rows"] += 1
            a["t_max"] = max(a["t_max"], t)
            a["modes_seen"].add(mode)
            a["pend_min"] = min(a["pend_min"], pend)
            a["pend_max"] = max(a["pend_max"], pend)

            # Track mode transitions
            if mode != a["prev_mode"]:
                a["mode_changes"].append((t, a["prev_mode"], mode))

            # Track LQR state
            if mode == 4:
                if not a["in_lqr"]:
                    a["lqr_entries"].append(t)
                a["in_lqr"] = True
            elif a["in_lqr"] and mode != 4:
                a["lqr_losses"] += 1
                a["lqr_loss_times"].append(t)
                a["in_lqr"] = False

            a["prev_mode"] = mode

    return attempts


def classify(attempts: dict[tuple[int, int], dict]) -> dict[tuple[int, int], str]:
    """Classify each attempt from raw mode data."""
    classifications = {}
    for key, a in attempts.items():
        has_lqr = len(a["lqr_entries"]) > 0
        final_mode = a["prev_mode"]

        if not has_lqr:
            classifications[key] = "MISS"
        elif final_mode == 4 and a["lqr_losses"] == 0:
            classifications[key] = "CATCH"
        elif final_mode == 4 and a["lqr_losses"] > 0:
            classifications[key] = "CHATTER"
        else:
            classifications[key] = "TRANSIENT"

    return classifications


def audit_quality(attempts: dict[tuple[int, int], dict], duration: float = 30, poll_hz: float = 10) -> list[dict]:
    """Audit data quality and return list of findings."""
    findings = []
    expected_samples = int(duration * poll_hz)

    for _key, a in sorted(attempts.items()):
        dur = a["t_max"] - a["t0"]
        rate = a["rows"] / dur if dur > 0 else 0

        # Poll rate check
        if rate < poll_hz * 0.7:
            findings.append(
                {
                    "severity": "HIGH",
                    "sp": a["sp"],
                    "attempt": a["attempt"],
                    "issue": f"Poll rate {rate:.1f}Hz < 70% of configured {poll_hz}Hz",
                }
            )

        # Truncation check
        if dur < duration - 2:
            findings.append(
                {
                    "severity": "HIGH",
                    "sp": a["sp"],
                    "attempt": a["attempt"],
                    "issue": f"Truncated: {dur:.1f}s vs {duration}s expected",
                }
            )

        # Sample count check
        if abs(a["rows"] - expected_samples) > expected_samples * 0.1:
            findings.append(
                {
                    "severity": "MEDIUM",
                    "sp": a["sp"],
                    "attempt": a["attempt"],
                    "issue": f"Sample count {a['rows']} vs expected ~{expected_samples}",
                }
            )

        # Unexpected modes
        unexpected = a["modes_seen"] - {0, 4, 5}
        if unexpected:
            findings.append(
                {
                    "severity": "CRITICAL",
                    "sp": a["sp"],
                    "attempt": a["attempt"],
                    "issue": f"Unexpected modes: {unexpected}",
                }
            )

    return findings


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data"

    sweep_dir = find_latest_sweep(data_dir)
    csv_path = sweep_dir / "sweep_data.csv"

    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    print("=== QUBE Sweep Analyzer + Auditor ===")
    print(f"Sweep: {sweep_dir.name}")
    print()

    # Load data
    attempts = load_sweep(csv_path)
    total_rows = sum(a["rows"] for a in attempts.values())
    print(f"Loaded {total_rows} samples across {len(attempts)} attempts")

    # Classify
    classifications = classify(attempts)

    # Audit quality
    findings = audit_quality(attempts)

    # Report
    sp_values = sorted(set(a["sp"] for a in attempts.values()))

    # --- Quality Report ---
    print()
    print("=" * 80)
    print("CALIDAD DE DATOS")
    print("=" * 80)

    rates = []
    for key in sorted(attempts.keys()):
        a = attempts[key]
        dur = a["t_max"] - a["t0"]
        rate = a["rows"] / dur if dur > 0 else 0
        rates.append(rate)
        flag = " TRUNCATED" if dur < 28 else ""
        print(f"  sp={a['sp']:>2} att={a['attempt']} rows={a['rows']:>3} dur={dur:>5.1f}s rate={rate:>5.1f}Hz{flag}")

    avg_rate = sum(rates) / len(rates)
    print(f"  Average poll rate: {avg_rate:.1f}Hz")
    print()

    # --- Classification Report ---
    print("=" * 80)
    print("CLASIFICACIÓN (reconstruida desde datos crudos)")
    print("=" * 80)

    for sp in sp_values:
        sp_keys = sorted(k for k in attempts if k[0] == sp)
        catches = sum(1 for k in sp_keys if classifications[k] == "CATCH")
        chatters = sum(1 for k in sp_keys if classifications[k] == "CHATTER")
        transients = sum(1 for k in sp_keys if classifications[k] == "TRANSIENT")
        misses = sum(1 for k in sp_keys if classifications[k] == "MISS")
        total = len(sp_keys)

        clean_rate = catches / total * 100
        total_rate = (catches + chatters) / total * 100

        print(f"\n  sp={sp}: {catches}C + {chatters}CH + {transients}T + {misses}M")
        print(f"    Clean catch rate: {clean_rate:.0f}%")
        print(f"    Total catch rate (incl chatter): {total_rate:.0f}%")

        for key in sp_keys:
            a = attempts[key]
            cls = classifications[key]
            lqr_t = f"lqr={a['lqr_entries'][0]:.1f}s" if a["lqr_entries"] else "no_lqr"
            loss_str = f" losses={a['lqr_losses']}" if a["lqr_losses"] > 0 else ""
            print(
                f"      att={a['attempt']} {cls:>9} max={max(abs(a['pend_min']), abs(a['pend_max'])):.0f}° "
                f"{lqr_t}{loss_str}"
            )

    # --- Findings ---
    print()
    print("=" * 80)
    print("HALLAZGOS DE AUDITORÍA")
    print("=" * 80)

    if not findings:
        print("  Sin hallazgos — datos OK")
    else:
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        high = [f for f in findings if f["severity"] == "HIGH"]
        medium = [f for f in findings if f["severity"] == "MEDIUM"]

        if critical:
            print(f"\n  CRITICAL ({len(critical)}):")
            for f in critical:
                print(f"    sp={f['sp']} att={f['attempt']}: {f['issue']}")
        if high:
            print(f"\n  HIGH ({len(high)}):")
            for f in high:
                print(f"    sp={f['sp']} att={f['attempt']}: {f['issue']}")
        if medium:
            print(f"\n  MEDIUM ({len(medium)}):")
            for f in medium:
                print(f"    sp={f['sp']} att={f['attempt']}: {f['issue']}")

    # --- Summary ---
    print()
    print("=" * 80)
    print("RESUMEN")
    print("=" * 80)

    best_sp = None
    best_rate = 0
    for sp in sp_values:
        sp_keys = [k for k in attempts if k[0] == sp]
        catches = sum(1 for k in sp_keys if classifications[k] == "CATCH")
        rate = catches / len(sp_keys) * 100
        if rate > best_rate:
            best_rate = rate
            best_sp = sp

    print(f"  Sweet spot: sp={best_sp} ({best_rate:.0f}% clean catch rate)")

    # METRIC lines for autoresearch integration
    print()
    for sp in sp_values:
        sp_keys = [k for k in attempts if k[0] == sp]
        catches = sum(1 for k in sp_keys if classifications[k] == "CATCH")
        chatters = sum(1 for k in sp_keys if classifications[k] == "CHATTER")
        misses = sum(1 for k in sp_keys if classifications[k] in ("MISS", "TRANSIENT"))
        total = len(sp_keys)
        print(f"METRIC sp_{sp}_clean_catches={catches}/{total}")
        print(f"METRIC sp_{sp}_chatter={chatters}/{total}")
        print(f"METRIC sp_{sp}_miss={misses}/{total}")

    print(f"METRIC best_sp={best_sp}")
    print(f"METRIC best_clean_rate={best_rate:.0f}")
    print(f"METRIC total_findings={len(findings)}")


if __name__ == "__main__":
    main()
