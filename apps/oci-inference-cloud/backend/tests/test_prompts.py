from app.prompts import (
    DEFAULT_PROMPT_SETS,
    generated_cold_long_csv,
    generated_decode_heavy_csv,
    generated_shared_prefix_csv,
    generated_shared_prefix_prompts,
    generated_unique_prefill_prompts,
    parse_prompt_file,
)


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


def test_lab1_prefill_diagnostics_have_unique_and_shared_prefix_variants() -> None:
    unique = parse_prompt_file(generated_unique_prefill_prompts(3, context_repetitions=2))
    shared = parse_prompt_file(generated_shared_prefix_prompts(3))

    assert len(unique) == 3
    assert len(shared) == 3
    assert len(set(unique)) == 3
    assert "Shared briefing" in shared[0]


def test_lab1_long_length_sweep_has_24_substantially_longer_unique_prompts() -> None:
    workload = next(item for item in DEFAULT_PROMPT_SETS if item["name"] == "TTFT length sweep · long unique prompts")
    prompts = parse_prompt_file(workload["text"])

    assert len(prompts) == 24
    assert len(set(prompts)) == 24
    assert min(len(prompt) for prompt in prompts) >= 5_000
