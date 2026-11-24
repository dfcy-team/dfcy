import hashlib
import json
import unittest
from datetime import date

from apps.integrations.feishu_finance_form import (
    FinanceFormError,
    parse_finance_form,
    validate_finance_file,
)


def form(date_value="2026-11-23", attachment=None):
    return [
        {"id": "actual", "type": "date", "value": date_value},
        {"id": "voucher", "type": "attachmentV2", "value": attachment if attachment is not None else [
            {"url": "https://files.invalid/download", "name": "receipt.pdf", "source_key": "synthetic-token"}
        ]},
        {"id": "plan-date", "type": "date", "value": "2099-01-01"},
        {"id": "application-files", "type": "attachment", "value": [{"url": "wrong", "name": "wrong.pdf", "source_key": "wrong"}]},
    ]


class FinanceFormTests(unittest.TestCase):
    def test_exact_configured_widgets_and_json_string(self):
        result = parse_finance_form(json.dumps(form()), date_widget_id="actual", voucher_widget_id="voucher")
        self.assertEqual(result["actual_payment_date"], date(2026, 11, 23))
        self.assertEqual(result["files"][0]["source_key"], "synthetic-token")

    def test_rfc3339_maps_to_shanghai_business_date(self):
        result = parse_finance_form(form("2026-11-22T17:30:00Z"), date_widget_id="actual", voucher_widget_id="voucher")
        self.assertEqual(result["actual_payment_date"], date(2026, 11, 23))

    def test_duplicate_missing_future_and_bad_date_rejected(self):
        for data in (form("2099-01-01"), form("2026-02-30"), form() + [form()[0]]):
            with self.subTest(data=data):
                with self.assertRaises(FinanceFormError):
                    parse_finance_form(data, date_widget_id="actual", voucher_widget_id="voucher")

    def test_empty_or_unrecognized_attachment_shape_rejected(self):
        for files in ([], [{"file_token": "opaque"}], ["opaque"]):
            with self.subTest(files=files), self.assertRaises(FinanceFormError):
                parse_finance_form(form(attachment=files), date_widget_id="actual", voucher_widget_id="voucher")

    def test_url_array_and_single_quoted_ext_filenames(self):
        data = form(attachment=["https://cdn.invalid/a?sig=one", "https://cdn.invalid/b?sig=two"])
        data[1]["ext"] = "'a.pdf','receipt, final.png'"
        result = parse_finance_form(data, date_widget_id="actual", voucher_widget_id="voucher")
        self.assertEqual([f["name"] for f in result["files"]], ["a.pdf", "receipt, final.png"])

    def test_signed_url_changes_keep_stable_source_key(self):
        def parse(signature):
            data = form(attachment=[f"https://CDN.invalid/path/file?signature={signature}#frag"])
            data[1]["ext"] = "'file.pdf'"
            return parse_finance_form(data, date_widget_id="actual", voucher_widget_id="voucher")["files"][0]
        self.assertEqual(parse("old")["source_key"], parse("rotated")["source_key"])
        self.assertNotIn("old", parse("old")["source_key"])

    def test_rejects_ext_mismatch_bad_urls_duplicate_keys_and_ambiguous_names(self):
        cases = []
        bad = form(attachment=["https://cdn.invalid/a", "https://cdn.invalid/b"])
        bad[1]["ext"] = "'a.pdf'"
        cases.append(bad)
        bad = form(attachment=["http://cdn.invalid/a"]); bad[1]["ext"] = "'a.pdf'"; cases.append(bad)
        bad = form(attachment=["https://user:pass@cdn.invalid/a"]); bad[1]["ext"] = "'a.pdf'"; cases.append(bad)
        bad = form(attachment=["https://cdn.invalid/a"]); bad[1]["ext"] = "'a.pdf','b.pdf'"; cases.append(bad)
        bad = form(attachment=[{"url": "https://cdn.invalid/a", "name": "a.pdf", "source_key": "same"},
                               {"url": "https://cdn.invalid/b", "name": "b.pdf", "source_key": "same"}]); cases.append(bad)
        bad = form(attachment=["https://cdn.invalid/a"]); bad[1]["ext"] = "'a.pdf"; cases.append(bad)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(FinanceFormError):
                parse_finance_form(data, date_widget_id="actual", voucher_widget_id="voucher")

    def test_validates_synthetic_pdf_magic_and_hash(self):
        body = b"%PDF-1.7\nsynthetic fixture"
        result = validate_finance_file(body, declared_name="C:\\temp\\pay\x00ment.pdf", content_type="application/pdf")
        self.assertEqual(result["filename"], "payment.pdf")
        self.assertEqual(result["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(result["byte_size"], len(body))

    def test_magic_extension_type_size_and_nonempty_enforced(self):
        cases = [
            (b"", "x.pdf", "application/pdf"),
            (b"not pdf", "x.pdf", "application/pdf"),
            (b"%PDF-x", "x.png", "application/pdf"),
            (b"%PDF-x", "x.pdf", "image/png"),
        ]
        for content, name, mime in cases:
            with self.subTest(content_len=len(content), name=name, mime=mime), self.assertRaises(FinanceFormError):
                validate_finance_file(content, declared_name=name, content_type=mime)
        self.assertEqual(validate_finance_file(b"%PDF-x", declared_name="x.pdf", content_type="application/pdf")["media_type"], "application/pdf")
        self.assertEqual(validate_finance_file(b"%PDF-x", declared_name="x.pdf", content_type="application/octet-stream")["media_type"], "application/pdf")
        with self.assertRaises(FinanceFormError):
            validate_finance_file(b"%PDF-x", declared_name="x.pdf", content_type="image/jpeg")
        with self.assertRaises(FinanceFormError):
            validate_finance_file(b"%PDF-" + b"x" * (20 * 1024 * 1024), declared_name="x.pdf", content_type="application/pdf")


if __name__ == "__main__":
    unittest.main()
