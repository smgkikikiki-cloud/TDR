import json
from datetime import date

from vehreg.serving_projection import build_model_serving_projection


def test_phase_e_payload_smoke():
    payload = build_model_serving_projection(
        "jaecoo.jaecoo_5_ev", as_of=date(2026, 9, 9)
    )
    print("PHASE_E_PAYLOAD=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    assert payload["projection_hash"]
