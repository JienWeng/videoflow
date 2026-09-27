"""Verified AtlasCloud model identifiers used by routing and capability checks."""

H3_REFERENCE_TO_VIDEO = "minimax/h3-developer/reference-to-video"
H3_TEXT_TO_VIDEO = "minimax/h3-developer/text-to-video"
H3_STANDARD_REFERENCE_TO_VIDEO = "minimax/h3/reference-to-video"

H3_REFERENCE_MODELS = frozenset(
    {H3_REFERENCE_TO_VIDEO, H3_STANDARD_REFERENCE_TO_VIDEO}
)
H3_DEVELOPER_MODELS = frozenset({H3_REFERENCE_TO_VIDEO, H3_TEXT_TO_VIDEO})


def is_h3_reference_model(model: str) -> bool:
    return model in H3_REFERENCE_MODELS
