#!/usr/bin/env python3
"""Render dither_bench.py's bench.json as one HTML page.

    bench_report.py "bench folder/bench.json" report.html [findings.html]
"""
import json
import sys

NAMES = {"dark": "Dark", "njad": "NotJustAnotherDither", "tpdfwide": "TPDFWide", "studiotan": "StudioTan",
         "spatialize": "SpatializeDither", "vinyl": "VinylDither", "tape": "TapeDither",
         "darkstereo": "DarkStereo 0.55 (прототип)", "paul": "PaulDither", "paulwide": "PaulWide", "tpdf": "TPDF (reference)", "round": "Rounding, no dither"}
# Dima's own description of each dither (2026-10-28), shown beside the numbers
HEARD = {
    "dark": "Темноватый, смягчает верх, благородный. Заметно сужает стереобазу.",
    "njad": "Ярче; стереобазу не меняет. Иногда выпячивается ~1 кГц.",
    "tpdfwide": "Расширяет стереобазу, но ~1 кГц проседает.",
    "studiotan": "Совсем не по-дизерному: всё на месте, но немного синтетично.",
    "spatialize": "",
    "darkstereo": "Прототип: Dark с развязкой каналов. Ещё не слушали.",
    "vinyl": "Звучит как винил; сужает стереобазу снизу.",
    "tape": "Что-то вроде сатурации на верхах, они немного проседают.",
}


def main(src, dst, findings=None):
    report = json.load(open(src))
    template = open(__file__.replace("bench_report.py", "bench_report.html")).read()
    data = {"report": report, "names": NAMES, "heard": HEARD}
    page = template.replace("/*DATA*/null", json.dumps(data))
    page = page.replace("<!--FINDINGS-->", open(findings).read() if findings else "")
    open(dst, "w").write(page)


if __name__ == "__main__":
    main(*sys.argv[1:4])
