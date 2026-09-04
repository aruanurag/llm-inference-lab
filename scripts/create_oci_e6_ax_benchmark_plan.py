from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUT = Path("docs/oci-e6-ax-cpu-inference-benchmark-plan.docx")

NAVY = "17365D"
BLUE = "DCEAF7"
PALE_BLUE = "F3F7FB"
PALE_GRAY = "F7F8FA"
GRID = "D9D9D9"
MUTED = RGBColor(89, 101, 112)
BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(255, 255, 255)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_borders(cell, color: str = GRID) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "6")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top: int = 100, start: int = 120, bottom: int = 100, end: int = 120) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    mar = tc_pr.first_child_found_in("w:tcMar")
    if mar is None:
        mar = OxmlElement("w:tcMar")
        tc_pr.append(mar)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = mar.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_text(cell, text: str, *, bold: bool = False, color: RGBColor = BLACK, size: int = 9, align=WD_ALIGN_PARAGRAPH.LEFT) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    run.font.size = Pt(size)
    run.font.color.rgb = color
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    set_cell_margins(cell)
    set_cell_borders(cell)


def set_column_width(cell, width_inches: float) -> None:
    cell.width = Inches(width_inches)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(width_inches * 1440)))
    tc_w.set(qn("w:type"), "dxa")


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        set_column_width(cell, widths[index])
        set_cell_shading(cell, NAVY)
        set_cell_text(cell, header, bold=True, color=WHITE, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    for row_index, row in enumerate(rows):
        cells = table.add_row().cells
        fill = "FFFFFF" if row_index % 2 == 0 else PALE_BLUE
        for index, value in enumerate(row):
            set_column_width(cells[index], widths[index])
            set_cell_shading(cells[index], fill)
            set_cell_text(cells[index], value, size=8)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def style_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.12

    for style_name, font_size, space_before, space_after in (("Title", 24, 0, 12), ("Heading 1", 15, 16, 7), ("Heading 2", 11.5, 11, 4)):
        style = styles[style_name]
        style.font.name = "Aptos Display" if style_name == "Title" else "Aptos"
        style._element.rPr.rFonts.set(qn("w:ascii"), style.font.name)
        style._element.rPr.rFonts.set(qn("w:hAnsi"), style.font.name)
        style.font.size = Pt(font_size)
        style.font.bold = True
        style.font.color.rgb = BLACK
        style.paragraph_format.space_before = Pt(space_before)
        style.paragraph_format.space_after = Pt(space_after)

    footer = section.footer
    footer_p = footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_p.paragraph_format.space_before = Pt(4)
    footer_run = footer_p.add_run("OCI CPU Inference Benchmark Plan  |  E6 Flex and E6 Ax Flex")
    footer_run.font.name = "Aptos"
    footer_run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    footer_run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    footer_run.font.size = Pt(8)
    footer_run.font.color.rgb = MUTED


def add_bullet(doc: Document, text: str, level: int = 0) -> None:
    paragraph = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.add_run(text)


def add_section_title(doc: Document, title: str) -> None:
    doc.add_heading(title, level=1)


def add_small_note(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = MUTED


def add_result_sheet(doc: Document) -> None:
    add_section_title(doc, "Result worksheet")
    doc.add_paragraph(
        "Complete this sheet after each matched pair run. Record the raw result path or exported experiment bundle separately; do not paste public IP addresses, SSH material, or OCI identifiers into a shareable result summary."
    )
    add_table(
        doc,
        ["Test", "Baseline E6 Flex", "E6 Ax Flex", "Change", "Interpretation and repeat status"],
        [
            ["T0 Runtime validation", "To complete", "To complete", "n/a", "Confirm inputs were matched"],
            ["T1 HTTP latency baseline", "To complete", "To complete", "To complete", "TTFT p95 and ITL p95"],
            ["T2 Cold prefill TTFT", "To complete", "To complete", "To complete", "Use unique long prompts"],
            ["T3 Prefill length sensitivity", "To complete", "To complete", "To complete", "Look for trend across input lengths"],
            ["T4 Decode pressure", "To complete", "To complete", "To complete", "Decode tok/s and approximate ITL"],
            ["T5 Concurrency scaling", "To complete", "To complete", "To complete", "Throughput versus p95 trade off"],
            ["T6 llama-bench", "To complete", "To complete", "To complete", "Prompt tok/s and decode tok/s only"],
            ["T7 vLLM bench serve", "To complete", "To complete", "To complete", "Serving TTFT, TPOT, throughput"],
        ],
        [1.0, 1.15, 1.15, 0.65, 2.55],
    )
    doc.add_heading("Conclusion to complete", level=2)
    doc.add_paragraph("Use the replicated results to state what improved, on which metric, under which engine and workload. Keep the conclusion limited to the tested configuration. A lower TTFT alone does not establish a general hardware cause, and native microbenchmark results should not be ranked against HTTP end to end results.")
    for _ in range(4):
        p = doc.add_paragraph("________________________________________________________________________________")
        p.paragraph_format.space_after = Pt(5)
        for run in p.runs:
            run.font.color.rgb = RGBColor(160, 168, 177)


def add_worksheet(
    doc: Document,
    number: int,
    title: str,
    objective: str,
    inputs: list[list[str]],
    result_headers: list[str],
    result_rows: list[list[str]],
    result_widths: list[float],
    note: str | None = None,
) -> None:
    """Add one independently runnable benchmark worksheet."""
    doc.add_page_break()
    add_section_title(doc, f"Worksheet {number}: {title}")
    doc.add_paragraph(objective)
    doc.add_heading("Required inputs — enter the actual values before you run", level=2)
    add_table(doc, ["Field", "Set in the lab", "Actual value / completion"], inputs, [1.55, 3.55, 1.9])
    doc.add_heading("Results to fill", level=2)
    add_table(doc, result_headers, result_rows, result_widths)
    if note:
        add_small_note(doc, note)


def paired_http_rows(
    trials: int = 3,
    completed: dict[tuple[int, str], list[str]] | None = None,
) -> list[list[str]]:
    rows: list[list[str]] = []
    for trial in range(1, trials + 1):
        for shape in ("E6 Flex", "E6 Ax Flex"):
            values = (completed or {}).get((trial, shape), ["", "", "", "", "", "", ""])
            rows.append([str(trial), shape, *values])
    return rows


def paired_native_rows(trials: int = 3) -> list[list[str]]:
    rows: list[list[str]] = []
    for trial in range(1, trials + 1):
        rows.append([str(trial), "E6 Flex", "", "", "", "", ""])
        rows.append([str(trial), "E6 Ax Flex", "", "", "", "", ""])
    return rows


def llama_http_inputs(
    prompt_set: str,
    concurrency: str,
    requests: str,
    max_tokens: str,
    server_state: str,
    actual_values: list[str] | None = None,
    server_settings: str = "Context 4096; parallel slots 4; batch 512; micro-batch 128; native build OFF; Disable VNNI ON",
) -> list[list[str]]:
    inputs = [
        ["Baseline instance", "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB", "________"],
        ["Candidate instance", "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB", "________"],
        ["Inference engine", "llama.cpp", "________"],
        ["Model", "Qwen2.5 1.5B Instruct Q4_K_M GGUF", "________"],
        ["Server settings", server_settings, "________"],
        ["Benchmark method", "HTTP streaming", "________"],
        ["Prompt set", prompt_set, "________"],
        ["Run values", f"Concurrency {concurrency}; requests {requests}; max tokens {max_tokens}", "________"],
        ["Server state", server_state, "________"],
    ]
    if actual_values:
        for row, actual_value in zip(inputs, actual_values):
            row[2] = actual_value
    return inputs


def vllm_inputs(prompt_set: str, concurrency: str, requests: str, max_tokens: str) -> list[list[str]]:
    return [
        ["Baseline instance", "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB", "________"],
        ["Candidate instance", "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB", "________"],
        ["Inference engine", "CPU vLLM", "________"],
        ["Model", "Qwen2.5 1.5B Instruct, BF16", "________"],
        ["Server settings", "Max model length 4096; max concurrent sequences 4; CPU KV cache 8 GiB", "________"],
        ["Benchmark method", "vLLM bench serve", "________"],
        ["Prompt set", prompt_set, "________"],
        ["Run values", f"Concurrency {concurrency}; requests {requests}; max tokens {max_tokens}", "________"],
        ["Repetitions", "Run the matched pair 3 times", "________"],
    ]


def add_guided_workbook(doc: Document) -> None:
    """Create the self-contained experiment cards used by the shareable plan."""
    doc.add_page_break()
    add_section_title(doc, "Guided benchmark worksheets")
    doc.add_paragraph(
        "Each worksheet below is self-contained. Select the listed settings in the Lab 1 comparison workflow, use Run on both shapes, and write the observed values in that worksheet immediately after the matched run completes. Do not change any setting listed as fixed while recording the three trials."
    )
    add_table(
        doc,
        ["Track", "Use it for", "Fixed deployment profile"],
        [
            ["llama.cpp", "HTTP serving tests and llama-bench microbenchmarks", "E6 Flex and E6 Ax Flex at 4 OCPUs / 32 GiB. Qwen2.5 1.5B Instruct Q4_K_M GGUF. Context 4096, slots 4, batch 512, micro-batch 128, native build OFF, Disable VNNI ON."],
            ["CPU vLLM", "vLLM bench serve confirmation tests", "E6 Flex and E6 Ax Flex at 4 OCPUs / 32 GiB. Qwen2.5 1.5B Instruct BF16. Max model length 4096, max concurrent sequences 4, CPU KV cache 8 GiB."],
        ],
        [1.1, 1.9, 4.0],
    )
    add_small_note(doc, "Record a trial only when both shapes complete successfully. Keep raw benchmark JSON files outside Git; write only a neutral local label in the Notes column.")

    add_worksheet(
        doc,
        1,
        "llama.cpp deployment and runtime check",
        "Use this worksheet to prove that both serving instances are matched before collecting performance data.",
        [
            ["Baseline instance", "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB", "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB; RUNNING"],
            ["Candidate instance", "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB", "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB; RUNNING"],
            ["Engine and model", "llama.cpp; Qwen2.5 1.5B Instruct Q4_K_M GGUF", "llama.cpp 0.4.0-dev, build 10811; Qwen2.5 1.5B Instruct Q4_K_M GGUF"],
            ["Build and CPU flags", "Native build OFF; Disable VNNI ON", "Native build OFF; VNNI disabled"],
            ["Server settings", "Context 4096; parallel slots 4; batch 512; micro-batch 128", "Context 4096; slots 4; batch 512; micro-batch 128"],
            ["Deployment check", "Both instances RUNNING; both health checks pass; endpoint responds", "Both instances RUNNING; health checks passed; endpoint responded"],
        ],
        ["Check", "Expected", "E6 Flex actual", "E6 Ax Flex actual", "Pass / note"],
        [
            ["OCPUs", "4", "4", "4", "Matched"],
            ["Memory", "32 GiB", "32 GiB", "32 GiB", "Matched"],
            ["nproc", "Record value", "8", "8", "Matched; SMT-visible CPUs"],
            ["Engine version", "Same version", "0.4.0-dev build 10811", "0.4.0-dev build 10811", "Matched"],
            ["Model file", "Same GGUF", "Qwen2.5 1.5B Instruct Q4_K_M", "Qwen2.5 1.5B Instruct Q4_K_M", "Matched"],
            ["Health check", "Pass", "Pass", "Pass", "Endpoint responded"],
        ],
        [1.25, 1.25, 1.35, 1.35, 1.8],
        "Parallel slots control request capacity. They do not reduce the CPU cores available to llama.cpp. The nproc values should be recorded before benchmarking.",
    )

    http_headers = ["Trial", "Shape", "OK / requests", "TTFT p50", "TTFT p95", "ITL p95", "Latency p95", "Req/s", "Output tok/s"]
    http_widths = [0.42, 0.82, 0.72, 0.72, 0.72, 0.67, 0.76, 0.55, 0.8]

    add_worksheet(
        doc,
        2,
        "llama.cpp HTTP baseline — short, unique prompts",
        "Measure the low-load end-to-end baseline. This uses one request at a time and short distinct prompts, so it is the starting point for comparing interactive serving.",
        llama_http_inputs(
            "TTFT length sweep · short unique prompts (24 distinct prompts)",
            "1",
            "24 — each prompt once",
            "128",
            "Freshly deployed process or stable warmed process; record which one",
            [
                "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "llama.cpp 0.4.0-dev, build 10811",
                "Qwen2.5 1.5B Instruct Q4_K_M GGUF",
                "Configured: context 4096; slots 4; batch 512; micro-batch 128; native OFF; VNNI disabled",
                "HTTP streaming through SSH tunnel",
                "24 short unique prompts",
                "Concurrency 1; requests 24; max tokens 128",
                "Model warm; Trial 1 server-default prompt cache; Trials 2–3 cache disabled",
            ],
        ),
        http_headers,
        paired_http_rows(completed={
            (1, "E6 Flex"): ["24 / 24", "506.3 ms", "621.8 ms", "25.5 ms", "3.276 s", "0.310", "52.36"],
            (1, "E6 Ax Flex"): ["24 / 24", "506.5 ms", "606.9 ms", "24.8 ms", "3.294 s", "0.319", "53.73"],
            (2, "E6 Flex"): ["24 / 24", "690.5 ms", "796.8 ms", "24.4 ms", "3.487 s", "0.293", "49.07"],
            (2, "E6 Ax Flex"): ["24 / 24", "686.0 ms", "778.4 ms", "24.4 ms", "3.394 s", "0.303", "50.70"],
            (3, "E6 Flex"): ["24 / 24", "709.1 ms", "773.8 ms", "25.4 ms", "3.420 s", "0.294", "49.12"],
            (3, "E6 Ax Flex"): ["24 / 24", "690.8 ms", "788.4 ms", "24.3 ms", "3.392 s", "0.304", "50.79"],
        }),
        http_widths,
        "All three matched pairs were imported from 4 September 2026. Trial 1 used the historical server-default cache behavior. Trials 2 and 3 sent cache_prompt=false, preventing request prompt-cache reuse. TTFT p95 is the primary reading; approximate ITL p95 is the decode indicator.",
    )

    add_worksheet(
        doc,
        3,
        "llama.cpp HTTP prefill — medium, unique prompts",
        "Measure how a medium input changes time to first token. Keep the output cap small so prompt processing is the main difference between this worksheet and the short-input baseline.",
        llama_http_inputs(
            "TTFT length sweep · medium unique prompts (24 distinct prompts; about 430 planning tokens each)",
            "1",
            "24 — each prompt once",
            "128",
            "Warm model weights only with unrecorded traffic; do not send this prompt set before the recorded trial",
            [
                "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "llama.cpp 0.4.0-dev, build 10811",
                "Qwen2.5 1.5B Instruct Q4_K_M GGUF",
                "Configured: context 4096; slots 4; batch 512; micro-batch 128; native OFF; VNNI disabled",
                "HTTP streaming through SSH tunnel",
                "24 medium unique prompts",
                "Concurrency 1; requests 24; max tokens 128",
                "Model warm; request prompt cache disabled",
            ],
        ),
        http_headers,
        paired_http_rows(completed={
            (1, "E6 Flex"): ["24 / 24", "2141.4 ms", "2242.0 ms", "26.6 ms", "5.001 s", "0.203", "34.05"],
            (1, "E6 Ax Flex"): ["24 / 24", "2138.6 ms", "2207.0 ms", "25.1 ms", "4.896 s", "0.207", "34.74"],
            (2, "E6 Flex"): ["24 / 24", "2131.5 ms", "2239.9 ms", "26.4 ms", "5.000 s", "0.202", "33.97"],
            (2, "E6 Ax Flex"): ["24 / 24", "2138.4 ms", "2221.3 ms", "24.4 ms", "4.881 s", "0.207", "34.84"],
            (3, "E6 Flex"): ["24 / 24", "2150.3 ms", "2358.9 ms", "26.1 ms", "5.137 s", "0.202", "33.90"],
            (3, "E6 Ax Flex"): ["24 / 24", "2158.7 ms", "2237.3 ms", "24.9 ms", "4.949 s", "0.207", "34.74"],
        }),
        http_widths,
        "All three matched pairs were imported from 4 September 2026 with cache_prompt=false. The planning token count is a guide, not the tokenizer's exact count. Compare this worksheet to the short and long unique-prompt worksheets using TTFT p95.",
    )

    add_worksheet(
        doc,
        4,
        "llama.cpp HTTP prefill — long, unique prompts",
        "Measure the most prefill-heavy serving case. The prompts are deliberately long and distinct, which avoids making KV reuse the explanation for a lower TTFT. Use one parallel slot so the full context is available to each long request.",
        llama_http_inputs(
            "TTFT length sweep · long unique prompts (24 distinct prompts; about 1,500 planning tokens each)",
            "1",
            "24 — each prompt once",
            "128",
            "Warm model weights only with unrecorded traffic; do not run the shared-prefix prompt set first.",
            [
                "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "llama.cpp 0.4.0-dev, build 10811",
                "Qwen2.5 1.5B Instruct Q4_K_M GGUF",
                "Configured: context 4096; slots 1; batch 512; micro-batch 128; native OFF; VNNI disabled",
                "HTTP streaming through SSH tunnel",
                "24 long unique prompts",
                "Concurrency 1; requests 24; max tokens 128",
                "Model warm; request prompt cache disabled",
            ],
            server_settings="Context 4096; parallel slots 1; batch 512; micro-batch 128; native build OFF; Disable VNNI ON",
        ),
        http_headers,
        paired_http_rows(completed={
            (1, "E6 Flex"): ["24 / 24", "7106.9 ms", "7214.5 ms", "28.5 ms", "10.218 s", "0.100", "16.07"],
            (1, "E6 Ax Flex"): ["24 / 24", "7059.6 ms", "7151.5 ms", "26.7 ms", "10.099 s", "0.101", "16.37"],
            (2, "E6 Flex"): ["24 / 24", "7102.2 ms", "7121.5 ms", "27.9 ms", "10.263 s", "0.099", "16.04"],
            (2, "E6 Ax Flex"): ["24 / 24", "7027.5 ms", "7058.3 ms", "27.1 ms", "10.018 s", "0.102", "16.41"],
            (3, "E6 Flex"): ["24 / 24", "7103.8 ms", "7119.2 ms", "28.2 ms", "10.256 s", "0.099", "16.05"],
            (3, "E6 Ax Flex"): ["24 / 24", "7024.0 ms", "7040.2 ms", "26.2 ms", "10.006 s", "0.102", "16.42"],
        }),
        http_widths,
        "All three successful trials were imported from 4 September 2026 with context 4096, one slot, and cache_prompt=false. The historical four-slot run is excluded: it provided only 1024 tokens per slot, while the selected prompts needed about 1183 to 1184 tokens. Compare TTFT p95 across the three trials; the Ax shape is lower in each recorded run.",
    )

    add_worksheet(
        doc,
        5,
        "llama.cpp HTTP decode pressure — long outputs",
        "Measure generation-heavy serving. The requests use short inputs and request long outputs, so inter-token behavior and output throughput matter more than prefill.",
        llama_http_inputs(
            "Long decode prompts",
            "1",
            "24 — each prompt once",
            "512",
            "Use the same deployment state for all three paired trials.",
            [
                "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB; RUNNING",
                "llama.cpp 0.4.0-dev, build 10811",
                "Qwen2.5 1.5B Instruct Q4_K_M GGUF",
                "Configured: context 4096; slots 1; batch 512; micro-batch 128; native OFF; VNNI disabled",
                "HTTP streaming through SSH tunnel",
                "Long decode prompts",
                "Concurrency 1; requests 24; max tokens 512",
                "Model warm; request prompt cache disabled",
            ],
            server_settings="Context 4096; parallel slots 1; batch 512; micro-batch 128; native build OFF; Disable VNNI ON",
        ),
        http_headers,
        paired_http_rows(completed={
            (1, "E6 Flex"): ["24 / 24", "313.5 ms", "336.6 ms", "29.5 ms", "11.628 s", "0.097", "51.53"],
            (1, "E6 Ax Flex"): ["24 / 24", "307.4 ms", "327.8 ms", "24.0 ms", "11.025 s", "0.102", "54.23"],
            (2, "E6 Flex"): ["24 / 24", "318.4 ms", "333.0 ms", "25.5 ms", "11.618 s", "0.097", "51.61"],
            (2, "E6 Ax Flex"): ["24 / 24", "309.2 ms", "326.6 ms", "25.2 ms", "11.044 s", "0.102", "54.15"],
            (3, "E6 Flex"): ["24 / 24", "319.0 ms", "337.0 ms", "27.7 ms", "11.597 s", "0.098", "51.70"],
            (3, "E6 Ax Flex"): ["24 / 24", "303.8 ms", "319.6 ms", "24.0 ms", "11.029 s", "0.102", "54.20"],
        }),
        http_widths,
        "All three successful trials were imported from 4 September 2026 with context 4096, one slot, and cache_prompt=false. The Ax shape has lower ITL p95 and higher output tok/s in every recorded trial. Approximate ITL is estimated from streamed response chunks, not a direct per-token clock.",
    )

    for number, concurrency, requests, label in [
        (6, "1", "24 — each prompt once", "single-request load"),
        (7, "4", "32 — prompts repeat only as required to reach 32 requests", "moderate load"),
        (8, "8", "64 — prompts repeat only as required to reach 64 requests", "sustained load"),
    ]:
        add_worksheet(
            doc,
            number,
            f"llama.cpp HTTP throughput — {label}",
            "Measure serving capacity at this one fixed concurrency. Keep all deployment settings unchanged while you compare aggregate work rate with tail latency.",
            llama_http_inputs("Throughput comparison prompts", concurrency, requests, "256", "Use the same deployed process for the complete three-trial worksheet"),
            http_headers,
            paired_http_rows(),
            http_widths,
            "A higher request rate or output-token rate is better only when the p95 TTFT and p95 latency remain acceptable. Record all fields before judging the winner.",
        )

    native_headers = ["Trial", "Shape", "Repetitions OK", "Prompt tok/s", "Decode tok/s", "Representative input", "Notes"]
    native_widths = [0.42, 0.9, 0.9, 0.95, 0.95, 1.25, 1.25]
    native_common = [
        ["Baseline instance", "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB", "________"],
        ["Candidate instance", "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB", "________"],
        ["Inference engine", "llama.cpp", "________"],
        ["Model", "Qwen2.5 1.5B Instruct Q4_K_M GGUF", "________"],
        ["Server build", "Context 4096; native build OFF; Disable VNNI ON", "________"],
        ["Benchmark method", "llama-bench", "________"],
    ]
    add_worksheet(
        doc,
        9,
        "llama-bench microbenchmark — prompt processing",
        "Measure llama.cpp prompt-processing throughput without the HTTP path. This is an engine microbenchmark, so use it alongside—not as a replacement for—the HTTP TTFT worksheets.",
        native_common + [
            ["Prompt set", "TTFT length sweep · long unique prompts", "________"],
            ["Run values", "Max tokens 128; repetitions 5", "________"],
            ["Concurrency field", "Any displayed UI concurrency is ignored by llama-bench", "________"],
        ],
        native_headers,
        paired_native_rows(),
        native_widths,
        "llama-bench creates a representative synthetic input length from the selected prompt set. Record the displayed length and prompt tok/s; it does not produce network TTFT.",
    )

    add_worksheet(
        doc,
        10,
        "llama-bench microbenchmark — token generation",
        "Measure llama.cpp generated-token throughput without the HTTP path. This isolates the decode-oriented native measurement.",
        native_common + [
            ["Prompt set", "Long decode prompts", "________"],
            ["Run values", "Max tokens 512; repetitions 5", "________"],
            ["Concurrency field", "Any displayed UI concurrency is ignored by llama-bench", "________"],
        ],
        native_headers,
        paired_native_rows(),
        native_widths,
        "Use decode tok/s as the key result. Do not compare its absolute value to HTTP ITL or to CPU vLLM TPOT; they measure different parts of the system.",
    )

    add_worksheet(
        doc,
        11,
        "CPU vLLM deployment and runtime check",
        "Use a fresh matched pair and confirm the vLLM configuration before serving benchmarks. Keep these results separate from the llama.cpp worksheets.",
        [
            ["Baseline instance", "VM.Standard.E6.Flex; 4 OCPUs; 32 GiB", "________"],
            ["Candidate instance", "VM.Standard.E6.Ax.Flex; 4 OCPUs; 32 GiB", "________"],
            ["Engine and model", "CPU vLLM; Qwen2.5 1.5B Instruct BF16", "________"],
            ["Server settings", "Max model length 4096; max concurrent sequences 4; CPU KV cache 8 GiB", "________"],
            ["Deployment check", "Both instances RUNNING; both health checks pass; endpoint responds", "________"],
        ],
        ["Check", "Expected", "E6 Flex actual", "E6 Ax Flex actual", "Pass / note"],
        [
            ["OCPUs", "4", "", "", ""],
            ["Memory", "32 GiB", "", "", ""],
            ["nproc", "Record value", "", "", ""],
            ["vLLM version", "Same version", "", "", ""],
            ["Health check", "Pass", "", "", ""],
        ],
        [1.25, 1.25, 1.35, 1.35, 1.8],
    )

    vllm_headers = ["Trial", "Shape", "OK / requests", "TTFT p95", "TPOT p95", "Latency p95", "Req/s", "Output tok/s", "Notes"]
    vllm_widths = [0.42, 0.82, 0.72, 0.72, 0.72, 0.76, 0.55, 0.8, 0.8]
    add_worksheet(
        doc,
        12,
        "CPU vLLM serving — prefill",
        "Measure vLLM serving time to first token for long unique prompts. This confirms the prefill observation with a second engine.",
        vllm_inputs("TTFT length sweep · long unique prompts", "1", "24 — each prompt once", "128"),
        vllm_headers,
        paired_http_rows(),
        vllm_widths,
        "vLLM bench serve derives a representative synthetic input length from the chosen prompt set. Record TTFT p95, request rate, and the tool's reported TPOT only within this vLLM track.",
    )

    add_worksheet(
        doc,
        13,
        "CPU vLLM serving — token generation",
        "Measure vLLM serving decode behavior at low concurrency. The long-output workload makes TPOT and output-token throughput the main results.",
        vllm_inputs("Long decode prompts", "1", "24 — each prompt once", "512"),
        vllm_headers,
        paired_http_rows(),
        vllm_widths,
        "TPOT is vLLM's time-per-output-token metric. A lower TPOT is better. Keep the model, KV cache setting, and max concurrent sequences fixed.",
    )

    add_worksheet(
        doc,
        14,
        "CPU vLLM serving — sustained load",
        "Measure vLLM serving capacity with eight active client requests. Record whether throughput improves without an unacceptable increase in tail latency or errors.",
        vllm_inputs("Throughput comparison prompts", "8", "64 — prompts repeat only as required to reach 64 requests", "256"),
        vllm_headers,
        paired_http_rows(),
        vllm_widths,
        "This measures an aggregate serving load, not a single interactive request. Compare results only to other CPU vLLM bench serve runs with the same settings.",
    )

    doc.add_page_break()
    add_section_title(doc, "Result summary to complete")
    doc.add_paragraph("After completing the worksheets, enter the median of the three trials below. This is the compact table to share with the team; keep the individual worksheet pages as the evidence behind it.")
    add_table(
        doc,
        ["Workload", "Method", "E6 Flex median", "E6 Ax Flex median", "Difference", "What it shows"],
        [
            ["Short unique prompt", "HTTP", "", "", "", "Low-load serving baseline"],
            ["Medium unique prompt", "HTTP", "", "", "", "Prefill sensitivity"],
            ["Long unique prompt", "HTTP", "", "", "", "Prefill-heavy TTFT"],
            ["Long output", "HTTP", "", "", "", "Decode-oriented serving"],
            ["Concurrency 8", "HTTP", "", "", "", "Aggregate throughput and tails"],
            ["Prompt microbenchmark", "llama-bench", "", "", "", "Native prompt tok/s"],
            ["Generation microbenchmark", "llama-bench", "", "", "", "Native decode tok/s"],
            ["Long unique prompt", "vLLM bench serve", "", "", "", "vLLM serving TTFT"],
            ["Long output", "vLLM bench serve", "", "", "", "vLLM serving TPOT"],
            ["Concurrency 8", "vLLM bench serve", "", "", "", "vLLM serving capacity"],
        ],
        [1.15, 1.15, 1.1, 1.1, 0.8, 1.2],
    )
    doc.add_heading("Conclusion to complete", level=2)
    doc.add_paragraph("State the tested engine, workload, primary metric, measured difference, and trial count. Avoid attributing a result to a specific hardware feature unless a separate controlled experiment proves that cause.")
    for _ in range(5):
        p = doc.add_paragraph("________________________________________________________________________________")
        p.paragraph_format.space_after = Pt(5)
        for run in p.runs:
            run.font.color.rgb = RGBColor(160, 168, 177)


def build_document() -> None:
    doc = Document()
    style_document(doc)

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.add_run("OCI E6 Ax and E6 Flex CPU Inference Benchmark Plan")

    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(18)
    run = subtitle.add_run("Matched CPU shape tests for llama.cpp and CPU vLLM serving")
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    run.font.size = Pt(13)
    run.font.color.rgb = MUTED

    add_table(
        doc,
        ["Prepared for", "Purpose", "Prepared date", "Document status"],
        [["Engineering review", "Compare inference performance with the same workload on OCI E6 Flex and E6 Ax Flex", date.today().strftime("%B %-d %Y"), "Test plan with outcome fields"]],
        [1.25, 3.35, 1.05, 1.1],
    )

    doc.add_heading("Purpose", level=1)
    doc.add_paragraph(
        "This plan measures whether an OCI E6 Ax Flex CPU shape changes inference serving performance relative to an E6 Flex shape when the workload and deployment are held constant. The intended outcome is a defensible comparison of prefill, decode, latency, and throughput behavior that the team can review and reproduce."
    )
    doc.add_paragraph(
        "This is an inference-system benchmark, not a model-quality evaluation. The same model should be used within each comparison. Accuracy, reasoning quality, or benchmark pass rates are out of scope unless a separate scored model-evaluation plan is added."
    )

    add_section_title(doc, "Decision questions")
    add_bullet(doc, "Does E6 Ax Flex improve time to first token for long, unique prompts when the model, OCPU allocation, memory, and server configuration are identical?")
    add_bullet(doc, "Does either shape improve decode throughput or inter-token latency for long outputs?")
    add_bullet(doc, "How does the difference change as concurrent requests increase?")
    add_bullet(doc, "Do engine-native measurements agree with the serving behavior measured through the application endpoint?")

    doc.add_page_break()
    add_section_title(doc, "Comparison design")
    doc.add_paragraph("Provision a matched CPU pair in the Lab 1 CPU shape comparison workflow. Treat the standard E6 Flex VM as the baseline and the E6 Ax Flex VM as the candidate. Reverse the run order between repetitions to reduce time-dependent bias.")
    add_table(
        doc,
        ["Item", "Baseline", "Candidate", "Requirement"],
        [
            ["OCI shape", "VM.Standard.E6.Flex", "VM.Standard.E6.Ax.Flex", "Same availability domain where possible"],
            ["OCPUs", "4", "4", "Required first series. Record the OCPU value from the instance table before benchmarking."],
            ["Memory", "32 GiB", "32 GiB", "Required first series. Keep the same 8 GiB per OCPU on both shapes."],
            ["Operating system image", "To complete", "Same image", "Same image ID and patch state"],
            ["Network and placement", "To complete", "Same subnet", "No public inference listener; keep server on loopback"],
            ["Model and weights", "To complete", "Same model artifact", "Same GGUF file for llama.cpp or same public model revision for vLLM"],
            ["Serving settings", "To complete", "Same settings", "Context, parallel slots or max sequences, cache, batch settings, and build mode"],
        ],
        [1.18, 1.55, 1.55, 2.47],
    )

    add_section_title(doc, "Lab implementation")
    doc.add_paragraph(
        "The current Lab 1 application provisions the two VM instances, deploys one selected engine and model configuration to both, and labels the two results as baseline and candidate. The application keeps the remote inference service on 127.0.0.1 port 8080 and uses an SSH tunnel for the HTTP streaming method. Raw benchmark artifacts remain outside the repository."
    )
    add_table(
        doc,
        ["Method", "What it measures", "Use for", "Do not use for"],
        [
            ["HTTP streaming end to end", "The client request path, streamed TTFT, approximate ITL, p95 latency, request rate, and output throughput", "Shape comparisons that represent application behavior", "Isolating CPU kernel performance"],
            ["llama-bench", "Direct llama.cpp prompt and generation token throughput with no network request", "Isolated llama.cpp prompt tok/s and decode tok/s", "TTFT, HTTP latency, queueing, or request rate"],
            ["vLLM bench serve", "Requests sent to the running vLLM service on the VM loopback interface", "vLLM serving TTFT, TPOT, request throughput, and output-token throughput", "Direct comparison with llama-bench values"],
        ],
        [1.25, 2.25, 1.55, 1.95],
    )
    add_small_note(doc, "The native tool integrations derive a representative synthetic input length from the selected prompt set. They do not send every prompt row. Use HTTP streaming whenever the exact prompt corpus must be executed.")

    doc.add_page_break()
    add_section_title(doc, "Execution controls")
    add_table(
        doc,
        ["Control", "How to apply it", "Why it matters"],
        [
            ["One variable at a time", "Change only the OCI shape within a paired test. Create a separate test block for OCPU count, model size, engine, or native build mode.", "Prevents the result from mixing shape and configuration effects."],
            ["Server state", "Deploy fresh on both shapes. Record whether the test is cold process, warmed process, or deliberately uses prompt-cache reuse.", "Warm weights and reusable KV state can materially change TTFT."],
            ["Prompt selection", "Use unique prompts for cold-prefill tests. Use repeated shared prefixes only in an explicitly labeled cache-reuse test.", "Avoids accidentally calling a cache effect a CPU-shape effect."],
            ["Thread visibility", "Record `nproc` and the engine-reported thread count. Parallel slots are request slots, not a CPU-thread limit.", "Confirms each VM had the intended CPU capacity."],
            ["Repetitions", "Run each paired test at least three times, alternating which shape runs first. Report median and range or p95 where available.", "Reduces sensitivity to transient host, network, and scheduling noise."],
            ["Tool boundary", "Compare results only within the same method and engine. Keep native microbenchmarks separate from end-to-end figures.", "The methods measure different portions of the serving system."],
        ],
        [1.25, 3.05, 2.7],
    )

    # The workbook pages below are the shareable, self-contained run instructions.
    # The earlier plan sections remain as source material while this document focuses
    # on the guided worksheets requested for the current benchmark campaign.
    add_guided_workbook(doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.core_properties.title = "OCI E6 Ax and E6 Flex CPU Inference Benchmark Plan"
    doc.core_properties.subject = "Matched inference performance test plan"
    doc.core_properties.author = ""
    doc.core_properties.comments = ""
    doc.save(OUT)
    return

    add_section_title(doc, "Prescriptive first execution")
    doc.add_paragraph("Run Series A first and fill its result worksheet before changing an engine, model, OCPU count, memory, or build mode. Run Series B only after Series A is complete. Each series compares E6 Flex with E6 Ax Flex; do not compare absolute values between the two engines.")
    add_table(
        doc,
        ["Series", "OCI pair", "Deploy exactly this", "Tests to run"],
        [
            ["A  llama.cpp required", "E6 Flex baseline and E6 Ax Flex candidate. 4 OCPUs and 32 GiB each; same image, AD, and subnet.", "Engine llama.cpp. Model Qwen2.5 1.5B Instruct Q4_K_M. Build native OFF. Disable VNNI ON. Context 4096. Parallel slots 4. Batch 512. Micro-batch 128.", "T0 through T6, plus D1. This is the primary shareable comparison."],
            ["B  CPU vLLM confirmation", "A fresh matched E6 Flex and E6 Ax Flex pair. 4 OCPUs and 32 GiB each; same image, AD, and subnet.", "Engine CPU vLLM. Model Qwen2.5 1.5B Instruct BF16. Max model length 4096. Max concurrent sequences 4. CPU KV cache 8 GiB.", "T0 through T5 and T7. Keep a separate result worksheet."],
        ],
        [1.18, 1.9, 3.0, 1.42],
    )

    doc.add_page_break()
    add_section_title(doc, "Required test matrix")
    doc.add_paragraph("Use Series A for T0 through T6. Repeat T0 through T5 as Series B and use T7 instead of T6. Use exactly the preset, prompt set, and run values below; modify settings only for an explicitly stated follow-up.")
    add_table(
        doc,
        ["ID", "Focus and method", "Lab input", "Run parameters", "Primary result"],
        [
            ["T0", "Deploy and validate the selected series", "No prompt set", "Deploy the profile above. Wait for both health checks. Record shape, 4 OCPUs, 32 GiB, image, engine version, model, build settings, context, and `nproc`.", "Matched configuration confirmed"],
            ["T1", "Low-load HTTP baseline", "TTFT length sweep short unique prompts", "HTTP streaming. Concurrency 1. Requests 24. Max tokens 128. Run the pair 3 times, alternating which shape runs first.", "TTFT p50 p95 p99; approximate ITL p95; latency p95"],
            ["T2", "Cold-prefill HTTP TTFT", "TTFT length sweep long unique prompts", "HTTP streaming. Concurrency 1. Requests 24. Max tokens 128. Warm model weights only with unrecorded traffic; then record 3 paired trials.", "TTFT p95 is primary; latency p95 is secondary"],
            ["T3", "Prefill input-length sweep", "TTFT length sweep short unique; medium unique; long unique", "HTTP streaming. For each of the 3 prompt sets: concurrency 1, requests 24, max tokens 128. Complete all three paired trials before moving to the next length.", "TTFT p50 p95 and trend by input length"],
            ["T4", "Decode-pressure HTTP run", "Long decode prompts", "HTTP streaming. Concurrency 1. Requests 24. Max tokens 512. Run 3 paired trials.", "Approximate ITL p95 and output tokens per second"],
            ["T5", "Load and throughput progression", "Throughput comparison prompts", "HTTP streaming. Run c1/r24, c4/r32, then c8/r64. Max tokens 256 for every run. Run each pair 3 times.", "Requests/sec and output tok/s with TTFT and latency p95"],
            ["T6", "llama.cpp native microbenchmark Series A only", "Long unique then Long decode prompts", "llama-bench. Prefill: long unique, max tokens 128, repetitions 5. Decode: long decode, max tokens 512, repetitions 5. The UI concurrency value is not used by llama-bench.", "Prompt tok/s for prefill; decode tok/s for generation"],
            ["T7", "vLLM serving benchmark Series B only", "Long unique then Long decode then Throughput comparison", "vLLM bench serve. Prefill c1/r24/max128; decode c1/r24/max512; load c8/r64/max256. Run each pair 3 times.", "TTFT, TPOT, request throughput, output token throughput"],
        ],
        [0.42, 1.4, 1.45, 2.1, 1.15],
    )

    add_section_title(doc, "Test procedures")
    doc.add_heading("T0 Runtime validation", level=2)
    doc.add_paragraph("Create a CPU shape comparison experiment. Set the E6 Flex baseline and E6 Ax Flex candidate to 4 OCPUs and 32 GiB each. For Series A, select llama.cpp and Qwen2.5 1.5B Instruct Q4_K_M, leave Build with GGML_NATIVE unchecked, leave Disable VNNI checked, and set context 4096, parallel slots 4, batch size 512, and micro-batch size 128. For Series B, select CPU vLLM and Qwen2.5 1.5B Instruct, with max model length 4096, max concurrent sequences 4, and CPU KV cache 8 GiB. Deploy the selected series to both shapes and capture the instance and deployment tables before benchmarking.")
    doc.add_heading("T1 Low load serving baseline", level=2)
    doc.add_paragraph("Select HTTP streaming and TTFT length sweep short unique. Confirm that the selected prompt set is TTFT length sweep short unique prompts. Keep concurrency 1, requests 24, and max tokens 128. Run the matched suite three times, alternating the shape that runs first. This is the low-load baseline and must finish with 24 successful requests per shape before you continue.")
    doc.add_heading("T2 Cold prefill TTFT", level=2)
    doc.add_paragraph("Select HTTP streaming and TTFT length sweep long unique. Confirm that the selected prompt set is TTFT length sweep long unique prompts. Keep concurrency 1, requests 24, and max tokens 128. Send a small amount of unrecorded traffic only to ensure model weights are resident, then run the 24 recorded prompts once each. Do not run the shared-prefix diagnostic before this test. Compare TTFT p95 across three replicated pairs.")
    doc.add_heading("T3 Prefill length sensitivity", level=2)
    doc.add_paragraph("Run the three presets in this order: TTFT length sweep short unique, medium unique, and long unique. For every point use HTTP streaming, concurrency 1, requests 24, and max tokens 128. The lab’s planning estimate is roughly 100, 430, and 1,500 input tokens respectively; actual model token counts may differ. This distinguishes a single long-prompt observation from a consistent prefill trend.")
    doc.add_heading("T4 Decode pressure", level=2)
    doc.add_paragraph("Select HTTP streaming and Long decode throughput. Confirm Long decode prompts, then set concurrency 1, requests 24, and max tokens 512. This creates short inputs with long requested completions so generation dominates the run. Interpret approximate ITL cautiously because the HTTP client estimates it from gaps between non-empty streamed chunks.")
    doc.add_heading("T5 Concurrency scaling", level=2)
    doc.add_paragraph("Select HTTP streaming and Throughput comparison prompts. Set max tokens to 256 for each run. Run c1 with 24 requests, c4 with 32 requests, then c8 with 64 requests. The Sustained load 64 requests preset sets the final c8/r64 point automatically. Repeat every matched pair three times. Hold the model and server configuration constant. Report both the throughput gain and any increase in p95 TTFT or p95 latency; the fastest aggregate throughput may not be the best interactive setting.")

    doc.add_page_break()
    add_section_title(doc, "Optional diagnostic presets")
    doc.add_paragraph("These tests explain a result; they do not replace the matched baseline suite. Label their outcomes separately in the final report.")
    add_table(
        doc,
        ["ID", "Preset or change", "How to run it", "What it answers"],
        [
            ["D1", "Shared prefix reuse diagnostic", "Run 24 shared-prefix prompts at concurrency 1 after T2. Compare the trend with the unique long-prompt baseline and record any engine-reported cache behavior.", "Whether repeated input or cache reuse changes TTFT. Do not use it as the cold-prefill shape result."],
            ["D2", "Larger-model confirmation", "Create a separate llama.cpp pair: Qwen2.5 7B Instruct Q4_K_M, 8 OCPUs, 64 GiB, portable build, context 4096, slots 4, batch 512, micro-batch 128. Run T2, T4, and T5 exactly.", "Whether the result is still present in a more demanding but separately controlled series."],
            ["D3", "OCPU scaling series", "Keep Series A model and llama.cpp settings unchanged. Create a second pair at 8 OCPUs and 64 GiB, then run T2, T4, and T5 exactly. Do not mix this worksheet with the 4-OCPU series.", "Whether the observed advantage scales, saturates, or reverses with available CPU capacity."],
            ["D4", "Placement isolation follow-up", "After VM trials, repeat the most informative T2 and T4 cases on comparably configured bare metal where capacity permits. Treat this as a separate test environment.", "Whether VM host interference plausibly influenced the VM comparison."],
        ],
        [0.4, 1.5, 3.1, 2.3],
    )

    doc.add_page_break()
    add_section_title(doc, "Engine specific procedures")
    doc.add_heading("llama.cpp with llama-bench", level=2)
    doc.add_paragraph("Use this only after deploying llama.cpp with the GGUF model. The tool runs directly against the model on the VM. A long input and short output case emphasizes prompt processing. A short input and long output case emphasizes decode. Its result is a CPU and engine microbenchmark, not an API experience. Record prompt tok/s and decode tok/s in separate columns from HTTP results.")
    add_table(
        doc,
        ["Microbenchmark case", "Input pattern", "Output pattern", "Result to record"],
        [
            ["L1 Prefill oriented", "Series A. Select TTFT length sweep long unique prompts. The lab supplies its representative average input length to llama-bench.", "Max tokens 128; repetitions 5", "Prompt tok/s, repetitions, `nproc`, and the displayed representative input length"],
            ["L2 Decode oriented", "Series A. Select Long decode prompts. The lab supplies its representative average input length to llama-bench.", "Max tokens 512; repetitions 5", "Decode tok/s, repetitions, `nproc`, and the displayed representative input length"],
        ],
        [1.4, 2.25, 1.25, 1.62],
    )
    doc.add_heading("CPU vLLM with vLLM bench serve", level=2)
    doc.add_paragraph("Use this only after deploying CPU vLLM with the same public model revision on both shapes. The command benchmarks the running local vLLM service and returns serving metrics. Keep the selected prompt length, output length, concurrency, CPU KV-cache capacity, max model length, and max concurrent sequences equal across the pair. Use TPOT as the serving-side time-per-output-token measure; do not compare it numerically with llama-bench decode tok/s.")
    add_table(
        doc,
        ["vLLM case", "Input and output", "Concurrency", "Result to record"],
        [
            ["V1 Serving prefill", "Series B. Select TTFT length sweep long unique prompts; 24 requests; 128 output tokens", "1", "TTFT p50 p95 p99, request throughput"],
            ["V2 Serving decode", "Series B. Select Long decode prompts; 24 requests; 512 output tokens", "1", "TPOT p50 p95, output token throughput"],
            ["V3 Serving load", "Series B. Select Throughput comparison prompts; 64 requests; 256 output tokens", "8", "Throughput, TTFT p95, TPOT p95, errors"],
        ],
        [1.2, 2.6, 0.8, 1.92],
    )

    doc.add_page_break()
    add_section_title(doc, "Metrics and interpretation")
    add_table(
        doc,
        ["Metric", "Meaning", "Use in this plan", "Caution"],
        [
            ["TTFT", "Elapsed time from request start to first streamed output token", "Primary prefill and interactivity metric", "Affected by prompt length, queueing, cache state, and network path"],
            ["Approximate ITL", "Estimated gap between non-empty streamed chunks", "Primary HTTP decode indicator", "Chunking means it is an approximation, not a direct per-token counter"],
            ["TPOT", "vLLM time per output token", "Primary vLLM serving decode indicator", "Compare only within vLLM bench serve"],
            ["Prompt tok/s", "llama-bench prompt processing throughput", "Native llama.cpp prefill indicator", "No request path, queueing, or TTFT"],
            ["Decode tok/s", "llama-bench generated-token throughput", "Native llama.cpp decode indicator", "No request path or API behavior"],
            ["Requests/sec and output tok/s", "Aggregate completed-work rate", "Concurrency capacity metric", "May improve while tail latency worsens"],
        ],
        [1.1, 2.1, 1.9, 1.42],
    )
    doc.add_paragraph("Interpret a result conservatively. If E6 Ax Flex has lower TTFT with similar ITL, the evidence supports faster prefill for the tested model and configuration. It does not prove a specific microarchitectural cause. Confirm with repeated trials, a second model size, and where possible a more isolated placement such as a bare metal follow-up.")

    add_section_title(doc, "Reporting package")
    doc.add_paragraph("Share the following with the team after results are complete:")
    add_bullet(doc, "The comparison design table with actual OCPU, memory, image, engine, model, and server settings filled in")
    add_bullet(doc, "One result worksheet per engine and OCPU series, including each repeated pair")
    add_bullet(doc, "A chart or table for TTFT p95, approximate ITL or TPOT, and output throughput for the HTTP and vLLM serving tests")
    add_bullet(doc, "A separate native llama-bench table showing prompt tok/s and decode tok/s")
    add_bullet(doc, "A short conclusion that states the tested workload, observed difference, replication count, and remaining uncertainty")

    doc.add_page_break()
    add_result_sheet(doc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.core_properties.title = "OCI E6 Ax and E6 Flex CPU Inference Benchmark Plan"
    doc.core_properties.subject = "Matched inference performance test plan"
    doc.core_properties.author = ""
    doc.core_properties.comments = ""
    doc.save(OUT)


if __name__ == "__main__":
    build_document()
