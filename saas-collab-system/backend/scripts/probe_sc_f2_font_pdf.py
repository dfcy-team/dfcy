import argparse
import hashlib
import json
import pathlib
import time
import tracemalloc

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=pathlib.Path)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1 or args.repeat > 50:
        raise ValueError("--repeat must be between 1 and 50.")

    manifest = json.loads(
        (args.bundle_dir / "manifest.json").read_text(encoding="utf-8")
    )
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    fonts = []
    for asset in manifest["assets"]:
        name = asset["postscript_name"]
        pdfmetrics.registerFont(TTFont(name, args.bundle_dir / asset["path"]))
        fonts.append((name, asset["role"]))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tracemalloc.start()
    started = time.perf_counter()
    pdf = canvas.Canvas(
        str(args.output),
        pagesize=(595.2756, 841.8898),
        invariant=1,
        pageCompression=1,
    )
    pdf.setCreator("SC-F2 font cross-environment probe")
    for _ in range(args.repeat):
        for font_name, role in fonts:
            pdf.setFont(font_name, 11)
            y = 800
            for sample in corpus["positive_samples"]:
                pdf.drawString(36, y, f"{role}:{sample['id']}: {sample['text']}")
                y -= 28
            pdf.showPage()
    pdf.save()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    _, peak_tracemalloc = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    payload = args.output.read_bytes()
    try:
        import resource

        max_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        max_rss_kib = None
    print(
        json.dumps(
            {
                "result": "PASS",
                "reportlab_version": reportlab.Version,
                "pages": len(fonts) * args.repeat,
                "positive_samples_per_page": len(corpus["positive_samples"]),
                "pdf_bytes": len(payload),
                "pdf_sha256": hashlib.sha256(payload).hexdigest(),
                "elapsed_ms": elapsed_ms,
                "python_tracemalloc_peak_bytes": peak_tracemalloc,
                "process_max_rss_kib": max_rss_kib,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
