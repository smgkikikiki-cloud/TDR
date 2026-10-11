"""Pure structural proposal gates. Results are proposals only, never writes."""


def evaluate_trim_change(action: str, *, model_current: bool, generation_exists: bool,
                         exact_thai_grade: bool = False, exact_powertrain: bool = False,
                         identity_collision: bool = False, corroborated_official: bool = False,
                         previously_confirmed_current: bool = False,
                         explicit_end_of_sale: bool = False,
                         complete_snapshots_days_apart: int = 0,
                         snapshots_independent: bool = False, source_conflict: bool = False,
                         owner_set_protected: bool = False, major_transition: bool = False,
                         whole_model_withdrawal: bool = False) -> dict:
    reasons = []
    if action == "ADD_TRIM":
        gates = [model_current, generation_exists, exact_thai_grade, exact_powertrain,
                 not identity_collision, corroborated_official, not owner_set_protected]
        reasons = ["ADD_GATE_FAILED"] if not all(gates) else ["OFFICIAL_IDENTITY_EVIDENCE"]
        eligible = all(gates)
    elif action == "DISCONTINUE_TRIM":
        negative_gate = explicit_end_of_sale or (snapshots_independent and complete_snapshots_days_apart >= 7)
        eligible = (model_current and generation_exists and previously_confirmed_current and negative_gate
                    and not source_conflict and not owner_set_protected and not major_transition
                    and not whole_model_withdrawal)
        if not eligible:
            reasons = ["DISCONTINUE_GATE_FAILED"]
        else:
            reasons = ["EXPLICIT_END_OF_SALE" if explicit_end_of_sale else "TWO_COMPLETE_SNAPSHOTS_7D"]
    else:
        return {"proposal": "REVIEW", "reason_codes": ["ACTION_REQUIRES_HUMAN_REVIEW"], "soft_archive_only": True}
    return {"proposal": "PROPOSE_" + action if eligible else "REVIEW",
            "reason_codes": reasons, "soft_archive_only": action == "DISCONTINUE_TRIM"}
