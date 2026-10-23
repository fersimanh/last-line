"""Fill the text cache (insight_cache.json) with agent explanations.

What it covers, for the Keeper's eyes view:
  key moments       saves, goals, claims, sweeps and notable distributions
  notable passes    every keeper pass, long forward passes, long balls and
                    passes that set up a shot (and passes lost in the own third)
  reports           the full-time keeper report for each club

It is resumable: anything already in the cache is skipped, so you can stop it
(Ctrl+C) and run it again to carry on. Texts are saved as soon as they come back.

    python3 build_cache.py --dry-run        # count the requests, call nothing
    python3 build_cache.py                  # fill everything that is missing
    python3 build_cache.py --only notable   # just the notable passes

You need to be signed in (az login). Do not run two fills at once: they would
overwrite each other's cache file.
"""
import argparse
import asyncio

import insights


def print_plan(views):
    plan = insights.plan_requests(views)
    print("Still to fill (agent requests: 1 Analyst + 1 Narrator + 1 per viewer, per event):")
    for part, count in plan.items():
        print(f"  {part:15} {count['events']:4} events -> {count['requests']:5} requests")
    total = sum(c["requests"] for c in plan.values())
    print(f"  {'total':15} {sum(c['events'] for c in plan.values()):4} events -> {total:5} requests")
    return plan


async def build(only, views):
    if only in ("all", "moments"):
        await insights.fill_missing(views)      # key moments, then the full-time reports
    if only in ("all", "notable"):
        await insights.fill_notable(views)


def main():
    parser = argparse.ArgumentParser(description="Fill the text cache with agent explanations.")
    parser.add_argument("--dry-run", action="store_true", help="count the requests; call nothing")
    parser.add_argument("--only", choices=["all", "moments", "notable"], default="all")
    args = parser.parse_args()
    views = insights.VIEWS
    plan = print_plan(views)
    if args.dry_run:
        return
    print("\nFilling...", flush=True)
    asyncio.run(build(args.only, views))
    print("\nDone. Left to fill:")
    print_plan(views)


if __name__ == "__main__":
    main()
