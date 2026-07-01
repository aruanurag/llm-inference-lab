from app.prompts import parse_prompt_file


def test_parse_prompt_file_splits_on_blank_lines() -> None:
    text = "Prompt one\n\nPrompt two\nline two\n\n\nPrompt three"

    assert parse_prompt_file(text) == ["Prompt one", "Prompt two\nline two", "Prompt three"]
