"""Run the engine over several seeds and print every metric against its target.

    python3 report_calibration.py              # 60 seeds, the engine's current stage
    python3 report_calibration.py --seeds 10   # a quicker look while tuning

PASS / FAIL per target (see calibration.py for the tolerances); targets a later
stage can measure print "n/a". The final line counts the failures.
"""
import argparse
import statistics
import time

import calibration
import sim_engine

STAGE = 3   # the stage the engine has reached; raise it as stages are finished


def run(seeds):
    per_match = []
    slowest = 0.0
    for seed in seeds:
        started = time.time()
        result = sim_engine.simulate(seed)
        slowest = max(slowest, time.time() - started)
        per_match.append(calibration.metrics_for(result))
    keys = {k for m in per_match for k in m}
    means = {k: statistics.mean(m[k] for m in per_match if k in m) for k in keys}
    return means, per_match, slowest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=60)
    args = parser.parse_args()
    means, per_match, slowest = run(range(1, args.seeds + 1))
    rows = calibration.evaluate(means, STAGE)
    print(f"Calibration: {args.seeds} seeds, engine stage {STAGE}. Slowest match {slowest:.1f} s (limit 60 s).")
    print(f"verified = {calibration.VERIFIED_SOURCE} (within 15%);  approximate = {calibration.APPROX_SOURCE} (within 25%)\n")
    print(f"{'metric':52} {'simulated':>10}  {'target':>13}  {'kind':11} {'':8}")
    for r in rows:
        target = (f"{r['value']:g}{r['unit']}" if r["kind"] == "verified"
                  else f"{r['value'][0]:g}-{r['value'][1]:g}{r['unit']}")
        measured = "-" if r["measured"] is None else f"{r['measured']:.1f}{r['unit']}"
        flag = "" if r["in_range"] is None else ("(in range)" if r["in_range"] else "(outside range)")
        print(f"{r['label']:52} {measured:>10}  {target:>13}  {r['kind']:11} {r['verdict']} {flag}")
    failed = [r for r in rows if r["verdict"] == "FAIL"]
    pending = [r for r in rows if r["verdict"].startswith("n/a")]
    print(f"\n{len(rows) - len(failed) - len(pending)} pass, {len(failed)} fail, {len(pending)} not measurable yet")
    return len(failed)


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
