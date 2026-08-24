import gzip
import re
import sys


PREFIX = "stg_devb_20260824_"
TABLE_TOKEN_RE = re.compile(
    r"(?P<head>(?:DROP TABLE IF EXISTS|CREATE TABLE|INSERT INTO|LOCK TABLES|ALTER TABLE)\s+`)"
    r"(?P<table>influencers_[A-Za-z0-9_]+)(?P<tail>`)"
)


def rewrite(source_path, output_path):
    opener = gzip.open if source_path.endswith(".gz") else open
    mode = "rt"
    with opener(source_path, mode, encoding="utf-8", errors="strict", newline="") as source:
        text = source.read()

    text = TABLE_TOKEN_RE.sub(
        lambda match: match.group("head") + PREFIX + match.group("table") + match.group("tail"),
        text,
    )
    text = re.sub(r"/\*!40000 ALTER TABLE .*? \*/;", "", text, flags=re.S)
    text = re.sub(r"\s*CONSTRAINT `[^`]+` FOREIGN KEY \([^\n]+\)(?:,)?", "", text)
    check_counter = iter(range(1, 10000))
    text = re.sub(
        r"CONSTRAINT `[^`]+` CHECK",
        lambda _match: f"CONSTRAINT `stg41_chk_{next(check_counter)}` CHECK",
        text,
    )
    text = re.sub(r",\s*\n\s*\) ENGINE=", "\n) ENGINE=", text)

    with open(output_path, "wt", encoding="utf-8", newline="\n") as output:
        output.write(text)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: rewrite_devb_staging.py SOURCE.sql[.gz] OUTPUT.sql")
    rewrite(sys.argv[1], sys.argv[2])
