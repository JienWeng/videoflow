from app.schemas.conversation import ConversationPlan, ConversationTurn
from app.services.conversation_service import validate_conversation_plan


def _plan(*turns: ConversationTurn) -> ConversationPlan:
    return ConversationPlan(
        scene_summary="Grace invites Mei to leave the meadow.",
        turns=list(turns),
        note="A short two-person exchange.",
    )


def test_validate_conversation_plan_accepts_ordered_cast_turns():
    plan = _plan(
        ConversationTurn(
            shot_index=0,
            speaker="Grace",
            line="Come with me.",
            visual_action="Grace reaches for Mei's hand.",
            emotion="hopeful",
        ),
        ConversationTurn(
            shot_index=1,
            speaker="Mei",
            line="I cannot leave.",
            visual_action="Mei pulls back and looks away.",
            emotion="guarded",
        ),
    )

    validated = validate_conversation_plan(
        plan, shot_count=2, allowed_speakers={"Grace", "Mei"}, max_words=6
    )

    assert [turn.speaker for turn in validated.turns] == ["Grace", "Mei"]


def test_validate_conversation_plan_rejects_unknown_speaker():
    plan = _plan(
        ConversationTurn(
            shot_index=0,
            speaker="Stranger",
            line="Follow me.",
            visual_action="A stranger points toward the road.",
            emotion="urgent",
        ),
    )

    try:
        validate_conversation_plan(
            plan, shot_count=1, allowed_speakers={"Grace"}, max_words=6
        )
    except ValueError as exc:
        assert "unknown speaker" in str(exc)
    else:
        raise AssertionError("unknown speakers must be rejected")


def test_validate_conversation_plan_rejects_wrong_turn_count_and_long_line():
    plan = _plan(
        ConversationTurn(
            shot_index=0,
            speaker="Grace",
            line="This line has far too many words for the configured limit.",
            visual_action="Grace gestures.",
            emotion="excited",
        ),
    )

    try:
        validate_conversation_plan(
            plan, shot_count=2, allowed_speakers={"Grace"}, max_words=6
        )
    except ValueError as exc:
        message = str(exc)
        assert "one turn per shot" in message
        assert "too long" in message
    else:
        raise AssertionError("invalid plans must be rejected")


def test_validate_conversation_plan_enforces_explicit_speaker_order():
    plan = _plan(
        ConversationTurn(
            shot_index=0,
            speaker="Mei",
            line="Not today.",
            visual_action="Mei folds her arms.",
        ),
        ConversationTurn(
            shot_index=1,
            speaker="Grace",
            line="Please listen.",
            visual_action="Grace steps closer.",
        ),
    )

    try:
        validate_conversation_plan(
            plan,
            shot_count=2,
            allowed_speakers={"Grace", "Mei"},
            max_words=6,
            speaker_order=["Grace", "Mei"],
        )
    except ValueError as exc:
        assert "must be spoken by 'Grace'" in str(exc)
    else:
        raise AssertionError("explicit speaker order must be enforced")
