from app.prompts import generated_cold_long_csv, generated_decode_heavy_csv, generated_shared_prefix_csv, parse_prompt_file


def test_parse_prompt_file_splits_on_blank_lines() -> None:
    text = "Prompt one\n\nPrompt two\nline two\n\n\nPrompt three"

    assert parse_prompt_file(text) == ["Prompt one", "Prompt two\nline two", "Prompt three"]


def test_parse_prompt_file_reads_a_prompt_column_from_csv() -> None:
    text = "prompt,category\nExplain prefill,prefill\nExplain decode,decode\n"

    assert parse_prompt_file(text, "workload.csv") == ["Explain prefill", "Explain decode"]


def test_parse_prompt_file_rejects_csv_without_a_supported_column() -> None:
    text = "question,category\nWhy,prefill\n"

    try:
        parse_prompt_file(text, "workload.csv")
    except ValueError as exc:
        assert "prompt" in str(exc)
    else:
        raise AssertionError("Expected a CSV header validation error")


def test_targeted_csv_workloads_have_the_requested_number_of_rows() -> None:
    assert len(parse_prompt_file(generated_shared_prefix_csv(3), "warm.csv")) == 3
    assert len(parse_prompt_file(generated_cold_long_csv(4), "cold.csv")) == 4
    assert "Do not answer in fewer than 300 words" in generated_decode_heavy_csv(1)
