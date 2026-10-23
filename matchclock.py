"""The match clock the viewer sees.

The engine runs on one continuous clock in seconds (`t`), half-time gap removed.
Fans see something else: the first half is 0:00 to 45:00, then added time shown as
"45+2:10"; the second half starts again at 45:00 and runs to 90:00, then "90+3:25".
`half2_start` is the engine second at which the second half kicks off.
"""
HALF = 2700   # 45 minutes
FULL = 5400   # 90 minutes


def display_clock(seconds, half2_start):
    second_half = half2_start > 0 and seconds >= half2_start
    shown = int(HALF + (seconds - half2_start)) if second_half else int(seconds)
    base = FULL if second_half else HALF
    if shown < base:
        return f"{shown // 60:02d}:{shown % 60:02d}"
    extra = shown - base
    return f"{base // 60}+{extra // 60}:{extra % 60:02d}"
