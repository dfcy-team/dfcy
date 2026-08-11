import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend" / "scripts" / "verify_sc_f2_label_renderer_contract.py"
CONTRACT = (
    ROOT
    / "docs"
    / "00_stage0"
    / "review"
    / "assets"
    / "scm_f2_label_renderer_contract_v1.json"
)


def test_sc_f2_label_renderer_contract_is_machine_verifiable():
    spec = importlib.util.spec_from_file_location("sc_f2_renderer_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.verify(ROOT, CONTRACT)

    assert result["result"] == "PASS"
    assert result["positive_codepoints"] == 105
    assert result["negative_samples"] == 6
    assert result["v1_preserved"] is True
    assert result["renderer_code_changed"] is False
