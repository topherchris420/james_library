import chat_with_james as james_chat


def test_parse_args_supports_greet_flag():
    args = james_chat.parse_args(["--greet"])
    assert args.greet is True


def test_build_prompt_includes_prior_assistant_greeting():
    prompt = james_chat.build_prompt(
        base_context="BASE",
        loaded_papers=[],
        conversation_history=[("assistant", james_chat.JAMES_GREETING)],
        user_message="Let's begin.",
    )
    assert james_chat.JAMES_GREETING in prompt
    assert "Christopher: Let's begin." in prompt
