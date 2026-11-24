from datetime import date
from decimal import Decimal
import json

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.integrations.feishu_payment_form import build_payment_form


def definition():
    return {"form": json.dumps([
        {"id": "reason", "name": "付款事由", "type": "textarea", "required": True},
        {"id": "kind", "name": "付款类型", "type": "radioV2", "required": True,
         "option": [{"value": "type-a", "text": "供应商货款"}]},
        {"id": "amount", "name": "付款金额", "type": "amount", "required": True,
         "option": {"currencyRange": ["CNY", "PHP"]}},
        {"id": "method", "name": "付款方式", "type": "radioV2", "required": True,
         "option": [{"value": "method-a", "text": "银行卡"}]},
        {"id": "date", "name": "付款日期", "type": "date", "required": True},
        {"id": "payee", "name": "收款人", "type": "input", "required": True},
        {"id": "bank", "name": "开户银行", "type": "input", "required": True},
        {"id": "account", "name": "收款账号", "type": "input", "required": True},
    ], ensure_ascii=False)}


class FeishuPaymentFormTests(SimpleTestCase):
    def build(self, **overrides):
        args = dict(reason="测试付款", amount=Decimal("12.34"), currency="CNY",
                    account_snapshot={"account_holder": "收款人", "bank_name": "银行", "account_number": "001234"},
                    payment_type="供应商货款", payment_method="银行卡", payment_date=date(2026, 11, 24))
        args.update(overrides)
        return build_payment_form(definition(), **args)

    def test_cny_php_amount_enum_values_date_and_account_string(self):
        for currency in ("CNY", "PHP"):
            with self.subTest(currency=currency):
                form = self.build(currency=currency)
                self.assertEqual(form[1]["value"], "type-a")
                self.assertEqual(form[2], {"id": "amount", "type": "amount", "value": 12.34, "currency": currency})
                self.assertEqual(form[3]["value"], "method-a")
                self.assertEqual(form[4]["value"], "2026-11-24T00:00:00+08:00")
                self.assertEqual(form[7]["value"], "001234")

    def test_ambiguous_enum_rejected(self):
        d = definition()
        widgets = json.loads(d["form"])
        widgets[1]["option"].append({"value": "type-b", "text": "供应商货款"})
        d["form"] = json.dumps(widgets, ensure_ascii=False)
        with self.assertRaises(ValidationError):
            build_payment_form(d, reason="x", amount=1, currency="CNY", account_snapshot={"recipient":"a", "bank":"b", "account":"c"}, payment_type="供应商货款", payment_method="银行卡", payment_date=date.today())

    def test_missing_and_unknown_required_widgets_rejected(self):
        d = definition()
        widgets = json.loads(d["form"])
        d["form"] = json.dumps(widgets[:-1], ensure_ascii=False)
        with self.assertRaises(ValidationError):
            build_payment_form(d, reason="x", amount=1, currency="CNY", account_snapshot={"account_holder":"a", "bank_name":"b", "account_number":"c"}, payment_type="type-a", payment_method="method-a", payment_date=date.today())
        d = definition()
        widgets = json.loads(d["form"])
        widgets.append({"id":"unknown", "name":"未知", "type":"input", "required":True})
        d["form"] = json.dumps(widgets, ensure_ascii=False)
        with self.assertRaises(ValidationError):
            build_payment_form(d, reason="x", amount=1, currency="CNY", account_snapshot={"account_holder":"a", "bank_name":"b", "account_number":"c"}, payment_type="type-a", payment_method="method-a", payment_date=date.today())

    def test_invalid_amount_currency_and_date_rejected(self):
        for amount in (0, -1, "NaN", "Infinity", "bad"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.build(amount=amount)
        with self.assertRaises(ValidationError):
            self.build(currency="USD")
        with self.assertRaises(ValidationError):
            self.build(payment_date="not-a-date")
        for invalid_date in (None, 20261124):
            with self.subTest(payment_date=invalid_date), self.assertRaises(ValidationError):
                self.build(payment_date=invalid_date)

    def test_amount_precision_loss_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.build(amount=Decimal("0.12345678901234567"))
