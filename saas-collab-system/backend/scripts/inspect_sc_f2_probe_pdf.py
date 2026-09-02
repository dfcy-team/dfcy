import argparse
import json

import pypdf
from pypdf.generic import ContentStream


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--corpus", required=True)
    args = parser.parse_args()

    with open(args.corpus, encoding="utf-8") as stream:
        corpus = json.load(stream)
    reader = pypdf.PdfReader(args.pdf)
    pages = []
    for index, page in enumerate(reader.pages):
        current_font = None
        drawn_fonts = set()
        content = ContentStream(page.get_contents(), reader)
        for operands, operator in content.operations:
            if operator == b"Tf":
                current_font = str(operands[0])
            elif operator in {b"Tj", b"TJ", b"'", b'"'} and current_font:
                drawn_fonts.add(current_font)

        fonts = []
        resources = page["/Resources"]
        for resource_name, font_reference in resources.get("/Font", {}).items():
            font = font_reference.get_object()
            descriptor = font.get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor else None
            fonts.append(
                {
                    "resource": str(resource_name),
                    "base_font": str(font.get("/BaseFont")),
                    "subtype": str(font.get("/Subtype")),
                    "to_unicode": "/ToUnicode" in font,
                    "font_file2": bool(descriptor and "/FontFile2" in descriptor),
                }
            )
        text = page.extract_text()
        pages.append(
            {
                "page": index + 1,
                "drawn_font_resources": sorted(drawn_fonts),
                "fonts": fonts,
                "missing_positive_samples": [
                    sample["id"]
                    for sample in corpus["positive_samples"]
                    if sample["text"] not in text
                ],
            }
        )

    checks = {
        "page_count": len(pages) >= 2,
        "text_extraction": all(not page["missing_positive_samples"] for page in pages),
        "embedded_truetype_with_tounicode": all(
            any(
                font["font_file2"]
                and font["to_unicode"]
                and "SCF2LabelSans" in font["base_font"]
                for font in page["fonts"]
            )
            for page in pages
        ),
        "no_helvetica_text_draw": all(
            "/F1" not in page["drawn_font_resources"] for page in pages
        ),
    }
    result = {
        "result": "PASS" if all(checks.values()) else "FAIL",
        "pypdf_version": pypdf.__version__,
        "checks": checks,
        "pages": pages,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
