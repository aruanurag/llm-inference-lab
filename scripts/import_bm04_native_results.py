from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


DOCX_PATH = Path("docs/oci-e6-ax-cpu-inference-benchmark-plan.docx")
BLACK = RGBColor(0, 0, 0)
MUTED = RGBColor(89, 101, 112)
WHITE = RGBColor(255, 255, 255)
NAVY = "1F4E79"
PALE_BLUE = "EAF2F8"


def set_cell_text(cell, text: str, *, bold: bool = False, color: RGBColor = BLACK) -> None:
    paragraph = cell.paragraphs[0]
    alignment = paragraph.alignment or WD_ALIGN_PARAGRAPH.LEFT
    paragraph.clear()
    paragraph.alignment = alignment
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    run.font.size = Pt(8)
    run.font.color.rgb = color
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def set_note(paragraph, text: str) -> None:
    paragraph.clear()
    paragraph.paragraph_format.space_after = Pt(6)
    run = paragraph.add_run(text)
    run.italic = True
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    run.font.size = Pt(9)
    run.font.color.rgb = MUTED


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_column_width(cell, width_inches: float) -> None:
    cell.width = Inches(width_inches)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(width_inches * 1440)))
    tc_w.set(qn("w:type"), "dxa")


def add_import_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float]):
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        set_column_width(cell, widths[index])
        set_cell_shading(cell, NAVY)
        set_cell_text(cell, header, bold=True, color=WHITE)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(values):
            set_column_width(cells[index], widths[index])
            set_cell_shading(cells[index], "FFFFFF" if row_index % 2 == 0 else PALE_BLUE)
            set_cell_text(cells[index], value)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def find_bm04_input_table(doc: Document):
    for index, table in enumerate(doc.tables):
        body = "\n".join(cell.text for row in table.rows for cell in row.cells)
        if "Bare metal native prompt and decode" in body and "Representative input" in body:
            return index, table
    raise RuntimeError("BM 04 inputs table was not found")


def find_bm04_results_table(doc: Document, start_index: int):
    for table in doc.tables[start_index + 1 :]:
        header = [cell.text for cell in table.rows[0].cells]
        if header == [
            "Trial", "Shape", "Reps OK", "Prompt tok/s", "Decode tok/s", "Representative input", "Notes"
        ]:
            return table
    raise RuntimeError("BM 04 results table was not found")


def find_table_with_text(doc: Document, required_text: str):
    for table in doc.tables:
        body = "\n".join(cell.text for row in table.rows for cell in row.cells)
        if required_text in body:
            return table
    raise RuntimeError(f"Table containing {required_text!r} was not found")


def find_table_index_with_text(doc: Document, required_text: str) -> int:
    for index, table in enumerate(doc.tables):
        body = "\n".join(cell.text for row in table.rows for cell in row.cells)
        if required_text in body:
            return index
    raise RuntimeError(f"Table containing {required_text!r} was not found")


def import_bm06_saturation(doc: Document) -> None:
    """Record the controlled cache-disabled serving-saturation repetitions."""
    input_index = find_table_index_with_text(doc, "Bare metal serving saturation; HTTP streaming")
    inputs = doc.tables[input_index]
    actual_values = {
        "Worker threads": "Generation 192; prefill 192 on both shapes.",
        "Server settings": "Context 4096; parallel slots 8; batch 512; micro-batch 128.",
        "Why context changes": "Context 4096 was held constant from the single-request tests to isolate queued serving behaviour.",
        "Prompt cache": "Disabled through the benchmark control; no redeploy required.",
        "Benchmark preset": "Bare metal serving saturation; HTTP streaming; Throughput comparison prompts (6 prompts).",
        "Run values": "Concurrency 8; requests 64; max tokens 256; matched run on both shapes.",
        "Repetitions": "Three complete matched pairs imported; 64 streamed requests completed on each shape per trial.",
    }
    for row in inputs.rows[1:]:
        if row.cells[0].text in actual_values:
            set_cell_text(row.cells[2], actual_values[row.cells[0].text])

    results = doc.tables[input_index + 1]
    if [cell.text for cell in results.rows[0].cells] != [
        "Trial", "Shape", "OK / requests", "TTFT p95", "ITL p95", "Latency p95", "Req/s", "Output tok/s", "Notes"
    ]:
        raise RuntimeError("BM 06 results table was not found immediately after its inputs")
    values = [
        ["1", "BM E6.256", "64 / 64", "619.4 ms", "43.1 ms", "8.12 s", "1.002", "324.95", "HTTP; cache off; 192/192; 63.87 s"],
        ["1", "BM E6 Ax.192", "64 / 64", "605.6 ms", "43.8 ms", "8.06 s", "1.008", "326.94", "HTTP; cache off; 192/192; 63.52 s"],
        ["2", "BM E6.256", "64 / 64", "595.7 ms", "43.8 ms", "7.97 s", "1.010", "330.55", "HTTP; cache off; 192/192; 63.39 s"],
        ["2", "BM E6 Ax.192", "64 / 64", "591.0 ms", "42.8 ms", "7.88 s", "1.024", "332.10", "HTTP; cache off; 192/192; 62.51 s"],
        ["3", "BM E6.256", "64 / 64", "594.3 ms", "45.0 ms", "7.98 s", "1.008", "331.45", "HTTP; cache off; 192/192; 63.46 s"],
        ["3", "BM E6 Ax.192", "64 / 64", "599.6 ms", "42.6 ms", "7.89 s", "1.020", "332.56", "HTTP; cache off; 192/192; 62.77 s"],
    ]
    for row, row_values in zip(results.rows[1:], values):
        for cell, value in zip(row.cells, row_values):
            set_cell_text(cell, value)

    bm06_heading = next(i for i, p in enumerate(doc.paragraphs) if p.text == "BM 06 Serving Saturation")
    for paragraph in doc.paragraphs[bm06_heading + 1 :]:
        if paragraph.style.name == "Heading 1":
            break
        if paragraph.text in {"Results to fill", "Imported results — first matched pair"}:
            paragraph.text = "Imported results — three controlled matched pairs"
            break

    for paragraph in doc.paragraphs[bm06_heading + 1 :]:
        if paragraph.style.name == "Heading 1":
            break
        if paragraph.text.startswith(("Collect end-to-end", "Three cache-disabled")):
            set_note(
                paragraph,
                "Three controlled cache-disabled matched pairs completed on 9 September 2026. Every trial completed 64/64 streamed requests at concurrency 8. E6 Ax.192 delivered 326.94–332.56 output tok/s versus 324.95–331.45 on E6.256, with lower p95 latency in every pair (7.88–8.06 vs 7.97–8.12 s). TTFT was close (591.0–605.6 vs 594.3–619.4 ms), so this workload shows a small but repeatable serving-throughput and end-to-end latency advantage rather than a large first-token difference.",
            )
            break


def import_bm05_decode(doc: Document) -> None:
    """Record the controlled 192-thread HTTP long-decode matched pair."""
    input_index = find_table_index_with_text(doc, "Long decode throughput; HTTP streaming; Long decode prompts")
    inputs = doc.tables[input_index]
    actual_values = {
        "Worker threads": "Generation 192; prefill 192 on both shapes.",
        "Server settings": "Context 4096; parallel slots 1; batch 512; micro-batch 128.",
        "Prompt cache": "Disabled through the benchmark control; no redeploy required.",
        "Benchmark preset": "Long decode throughput; HTTP streaming; Long decode prompts (3 prompts).",
        "Run values": "Concurrency 1; requests 4; max tokens 512; matched run on both shapes.",
        "Repetitions": "Three complete matched pairs imported; four streamed requests completed on each shape per trial.",
    }
    for row in inputs.rows[1:]:
        if row.cells[0].text in actual_values:
            set_cell_text(row.cells[2], actual_values[row.cells[0].text])

    results = doc.tables[input_index + 1]
    expected_header = [
        "Trial", "Shape", "OK / requests", "TTFT p95", "ITL p95", "Latency p95", "Req/s", "Output tok/s", "Notes"
    ]
    if [cell.text for cell in results.rows[0].cells] != expected_header:
        raise RuntimeError("BM 05 results table was not found immediately after its inputs")
    values = [
        ["1", "BM E6.256", "4 / 4", "126.1 ms", "24.1 ms", "11.02 s", "0.091", "51.42", "HTTP; cache disabled; 192/192 threads"],
        ["1", "BM E6 Ax.192", "4 / 4", "121.4 ms", "22.9 ms", "10.32 s", "0.097", "54.72", "HTTP; cache disabled; 192/192 threads"],
        ["2", "BM E6.256", "4 / 4", "119.1 ms", "24.2 ms", "10.99 s", "0.091", "51.40", "HTTP; cache disabled; 192/192 threads"],
        ["2", "BM E6 Ax.192", "4 / 4", "151.4 ms", "39.2 ms", "10.35 s", "0.097", "54.70", "HTTP; cache disabled; streaming outlier"],
        ["3", "BM E6.256", "4 / 4", "119.4 ms", "24.4 ms", "10.99 s", "0.091", "51.44", "HTTP; cache disabled; 192/192 threads"],
        ["3", "BM E6 Ax.192", "4 / 4", "119.3 ms", "23.0 ms", "10.32 s", "0.097", "54.70", "HTTP; cache disabled; 192/192 threads"],
    ]
    for row, row_values in zip(results.rows[1:], values):
        for cell, value in zip(row.cells, row_values):
            set_cell_text(cell, value)

    bm05_heading = next(i for i, p in enumerate(doc.paragraphs) if p.text == "BM 05 HTTP Decode Pressure")
    for paragraph in doc.paragraphs[bm05_heading + 1 :]:
        if paragraph.style.name == "Heading 1":
            break
        if paragraph.text in {"Results to fill", "Imported result — first matched pair", "Imported results — three matched pairs"}:
            paragraph.text = "Imported results — three matched pairs"
        if paragraph.text.startswith(("Primary metrics:", "At 192/192 threads,")):
            set_note(
                paragraph,
                "At 192/192 threads, all three cache-disabled pairs completed 4/4 long-output requests on both shapes. E6 Ax.192 sustained 54.70–54.72 output tok/s versus 51.40–51.44 on E6.256 (+6.4%) and lower end-to-end p95 latency (10.32–10.35 vs 10.99–11.02 s). One Ax streaming trial showed a higher ITL and TTFT outlier, while output throughput remained stable; interpret that as path-level variation rather than a decoder regression.",
            )


def restore_bm02_results(doc: Document) -> None:
    """Keep the corrected 32-thread cold-prefill trial data separate from BM 06."""
    input_index = find_table_index_with_text(doc, "CPU worker threads")
    results = doc.tables[input_index + 1]
    expected_header = [
        "Trial", "Shape", "OK / requests", "TTFT p95", "ITL p95", "Latency p95", "Req/s", "Output tok/s", "Notes"
    ]
    if [cell.text for cell in results.rows[0].cells] != expected_header:
        raise RuntimeError("BM 02 results table was not found immediately after its inputs")
    values = [
        ["1", "BM E6.256", "24 / 24", "5.19 s", "22.8 ms", "7.70 s", "0.13", "21.95", "Cache disabled; wall 183.91 s"],
        ["1", "BM E6 Ax.192", "24 / 24", "5.23 s", "22.4 ms", "7.74 s", "0.13", "22.09", "Cache disabled; wall 182.74 s"],
        ["2", "BM E6.256", "24 / 24", "5.21 s", "23.1 ms", "7.73 s", "0.13", "21.84", "Cache disabled; wall 184.81 s"],
        ["2", "BM E6 Ax.192", "24 / 24", "5.13 s", "23.6 ms", "7.50 s", "0.13", "22.46", "Cache disabled; wall 179.75 s"],
        ["3", "BM E6.256", "24 / 24", "5.22 s", "23.1 ms", "7.74 s", "0.13", "21.80", "Cache disabled; wall 185.20 s"],
        ["3", "BM E6 Ax.192", "24 / 24", "5.17 s", "21.8 ms", "7.62 s", "0.13", "22.27", "Cache disabled; wall 181.29 s"],
    ]
    for row, row_values in zip(results.rows[1:], values):
        for cell, value in zip(row.cells, row_values):
            set_cell_text(cell, value)


def import_bm03_thread_sweep(doc: Document) -> None:
    """Record the completed cache-disabled bare-metal thread-sweep screen points."""
    input_index = find_table_index_with_text(doc, "Bare metal cold long prefill; cache disabled; 24 long unique prompts")
    inputs = doc.tables[input_index]
    actual_values = {
        "Engine and model": "llama.cpp; Qwen2.5 7B Instruct Q4_K_M GGUF on both shapes.",
        "Build flags": "Native build OFF; Disable VNNI ON.",
        "Server settings": "Context 4096; parallel slots 1; batch 512; micro-batch 128.",
        "Benchmark": "HTTP streaming; cache disabled; 24 long unique prompts; concurrency 1; max tokens 128. Completed 16/16, 32/32, 64/64, 96/96, and 192/192 screen points.",
    }
    for row in inputs.rows[1:]:
        if row.cells[0].text in actual_values:
            set_cell_text(row.cells[2], actual_values[row.cells[0].text])

    results = doc.tables[input_index + 1]
    rows = {
        "16 / 16": ["9.11 s", "9.04 s", "14.10", "14.19", "Yes", "Median of 3 clean cache-disabled pairs (24/24 requests each)"],
        "32 / 32": ["5.21 s", "5.17 s", "21.84", "22.27", "Yes", "Screened; 3 cache-disabled pairs available"],
        "64 / 64": ["3.26 s", "3.23 s", "29.39", "29.82", "Yes", "Screened; Ax continued improving at 96/96"],
        "96 / 96": ["2.55 s", "2.41 s", "27.41", "34.94", "Yes", "Screened; Ax showed its largest relative output gain"],
        "192 / 192": ["1.92 s", "1.88 s", "36.61", "37.73", "Yes", "Final screen point; both hosts improved, Ax remained ahead"],
    }
    for row in results.rows[1:]:
        values = rows.get(row.cells[0].text)
        if values is None:
            continue
        for cell, value in zip(row.cells[1:], values):
            set_cell_text(cell, value)

    bm03_heading = next(i for i, p in enumerate(doc.paragraphs) if p.text == "BM 03 Thread Scaling")
    for paragraph in doc.paragraphs[bm03_heading + 1 :]:
        if paragraph.style.name == "Heading 1":
            break
        if paragraph.text in {"Screening results to fill", "Imported screening results — 32/32 and 64/64", "Imported screening results — 32/32, 64/64, and 96/96", "Imported screening results — 32/32, 64/64, 96/96, and 192/192"}:
            paragraph.text = "Imported screening results — 16/16, 32/32, 64/64, 96/96, and 192/192"
        if paragraph.text.startswith("Choose the two settings"):
            set_note(
                paragraph,
                "Cache-disabled screen points show a substantial gain from 32/32 to 64/64 on both hosts. At 96/96, BM E6.256 recorded 2.55 s TTFT p95 and 27.41 tok/s, while BM E6 Ax.192 recorded 2.41 s and 34.94 tok/s. The completed 192/192 point improved both hosts again: 1.92 s and 36.61 tok/s on BM E6.256, versus 1.88 s and 37.73 tok/s on BM E6 Ax.192. The 192/192 setting is the common configuration to carry into the next serving-facing test.",
            )
        if paragraph.text.startswith("Completed cache-disabled screen points"):
            set_note(
                paragraph,
                "At 16/16 threads, the three-trial median was closely matched: BM E6.256 reached 9.11 s TTFT p95 and 14.10 tok/s, while BM E6 Ax.192 reached 9.04 s and 14.19 tok/s. Cache-disabled screen points then show a substantial gain from 32/32 to 64/64 on both hosts. The final 192/192 point was the fastest common setting: BM E6.256 reached 1.92 s TTFT p95 and 36.61 tok/s; BM E6 Ax.192 reached 1.88 s and 37.73 tok/s. Carry 192/192 into the serving-facing tests, then repeat the chosen setting before declaring a winner.",
            )


def import_bm07_larger_model(doc: Document) -> None:
    """Record the completed 14B confirmation tests without local run metadata."""
    input_index = find_table_index_with_text(doc, "Qwen2.5 14B Instruct Q4_K_M GGUF")
    inputs = doc.tables[input_index]
    actual_values = {
        "Model": "Qwen2.5 14B Instruct Q4_K_M GGUF deployed on both shapes.",
        "Worker threads": "Generation 192; prefill 192 on both shapes.",
        "Build and server settings": "Native build OFF; VNNI disabled; context 4096; parallel slots 1; batch 512; micro-batch 128.",
        "Test A": "HTTP streaming; cache disabled; 24 long unique prompts; concurrency 1; 24 requests; max tokens 128.",
        "Test B": "llama-bench native prompt/decode; five repetitions; generation length 512.",
        "Repetitions": "Three complete matched pairs completed for each test; the individual trials are recorded below.",
    }
    for row in inputs.rows[1:]:
        if row.cells[0].text in actual_values:
            set_cell_text(row.cells[2], actual_values[row.cells[0].text])

    results = doc.tables[input_index + 1]
    expected_header = [
        "Workload", "Primary metric", "BM E6.256 median", "BM E6 Ax.192 median", "Difference", "Interpretation"
    ]
    if [cell.text for cell in results.rows[0].cells] != expected_header:
        raise RuntimeError("BM 07 results table was not found immediately after its inputs")
    values = [
        ["14B cold long prefill", "TTFT p95", "3.640 s", "3.600 s", "Ax 1.1% faster", "Small cache-cold first-token advantage; validate under concurrency."],
        ["14B native prompt", "Prompt tok/s", "426.07", "441.21", "Ax +3.6%", "Repeatable native prompt-processing advantage."],
        ["14B native decode", "Decode tok/s", "26.27", "26.67", "Ax +1.5%", "Near tie; a small Ax median advantage."],
    ]
    for row, row_values in zip(results.rows[1:], values):
        for cell, value in zip(row.cells, row_values):
            set_cell_text(cell, value)

    note = next((p for p in doc.paragraphs if p.text.startswith("Imported 14B results:")), None)
    if note is None:
        note = doc.add_paragraph()
    set_note(
        note,
        "Imported 14B results: cache-cold TTFT p95 by trial (E6.256 / E6 Ax.192) was 3.679 / 3.600, 3.637 / 3.616, and 3.640 / 3.486 s. Native prompt tok/s was 426.07 / 441.21, 426.56 / 443.17, and 423.05 / 431.49; native decode tok/s was 25.91 / 26.50, 27.27 / 26.67, and 26.27 / 26.96. Medians are reported in the table. This supports a modest prompt-side advantage on Ax; it is not evidence of a large decode advantage.",
    )


def import_bm08_larger_model_saturation(doc: Document) -> None:
    """Append and maintain the 14B cache-disabled concurrent-serving validation."""
    marker = "14B serving saturation; HTTP streaming"
    try:
        input_index = find_table_index_with_text(doc, marker)
    except RuntimeError:
        doc.add_page_break()
        doc.add_heading("BM 08 Larger-Model Serving Saturation", level=1)
        doc.add_paragraph(
            "This completes the larger-model confirmation under sustained concurrent serving. "
            "It uses the same 14B model and worker-thread setting as BM 07, while increasing "
            "server request capacity so queueing and end-to-end throughput are measured."
        )
        doc.add_heading("Required inputs", level=2)
        add_import_table(
            doc,
            ["Field", "Set in the lab", "Actual value / completion"],
            [
                ["Model", "Qwen2.5 14B Instruct Q4_K_M GGUF", "Qwen2.5 14B Instruct Q4_K_M GGUF on both shapes."],
                ["Worker threads", "Use the BM 03 winner", "Generation 192; prefill 192 on both shapes."],
                ["Server capacity", "Parallel slots 8; context 4096; batch 512; micro-batch 128", "Matched deployment completed with 8 parallel slots."],
                ["Workload", marker, "Throughput comparison prompts; HTTP streaming; cache disabled."],
                ["Run values", "Concurrency 8; requests 64; max tokens 256", "Three complete matched pairs; every side completed 64/64 requests."],
            ],
            [1.55, 3.35, 2.1],
        )
        doc.add_heading("Imported results — three matched pairs", level=2)
        add_import_table(
            doc,
            ["Trial", "Shape", "OK", "TTFT p95", "ITL p95", "Latency p95", "Req/s", "Output tok/s", "Notes"],
            [["", "", "", "", "", "", "", "", ""] for _ in range(6)],
            [0.35, 0.95, 0.47, 0.7, 0.66, 0.78, 0.53, 0.72, 1.17],
        )
        add_import_table(
            doc,
            ["Metric", "BM E6.256 median", "BM E6 Ax.192 median", "Difference", "Interpretation"],
            [["", "", "", "", ""] for _ in range(5)],
            [1.35, 1.32, 1.42, 1.05, 2.06],
        )
        input_index = find_table_index_with_text(doc, marker)

    results = doc.tables[input_index + 1]
    expected_header = [
        "Trial", "Shape", "OK", "TTFT p95", "ITL p95", "Latency p95", "Req/s", "Output tok/s", "Notes"
    ]
    if [cell.text for cell in results.rows[0].cells] != expected_header:
        raise RuntimeError("BM 08 per-trial results table was not found immediately after its inputs")
    values = [
        ["1", "BM E6.256", "64 / 64", "1.164 s", "58.7 ms", "14.86 s", "0.545", "182.13", "HTTP; cache off; 192/192; 117.37 s"],
        ["1", "BM E6 Ax.192", "64 / 64", "1.158 s", "57.5 ms", "14.44 s", "0.556", "186.70", "HTTP; cache off; 192/192; 115.10 s"],
        ["2", "BM E6.256", "64 / 64", "1.201 s", "59.1 ms", "14.88 s", "0.542", "181.66", "HTTP; cache off; 192/192; 118.07 s"],
        ["2", "BM E6 Ax.192", "64 / 64", "1.116 s", "60.9 ms", "14.29 s", "0.563", "187.64", "HTTP; cache off; 192/192; 113.58 s"],
        ["3", "BM E6.256", "64 / 64", "1.167 s", "58.4 ms", "14.81 s", "0.544", "183.17", "HTTP; cache off; 192/192; 117.58 s"],
        ["3", "BM E6 Ax.192", "64 / 64", "1.096 s", "56.5 ms", "14.22 s", "0.565", "187.59", "HTTP; cache off; 192/192; 113.21 s"],
    ]
    for row, row_values in zip(results.rows[1:], values):
        for cell, value in zip(row.cells, row_values):
            set_cell_text(cell, value)

    summary = doc.tables[input_index + 2]
    expected_summary_header = ["Metric", "BM E6.256 median", "BM E6 Ax.192 median", "Difference", "Interpretation"]
    if [cell.text for cell in summary.rows[0].cells] != expected_summary_header:
        raise RuntimeError("BM 08 median summary table was not found immediately after its results")
    summary_values = [
        ["TTFT p95", "1.167 s", "1.116 s", "Ax 4.4% lower", "Lower first-token tail under eight-way load."],
        ["ITL p95", "58.7 ms", "57.5 ms", "Ax 2.0% lower", "Small decode-chunk cadence advantage."],
        ["Latency p95", "14.86 s", "14.29 s", "Ax 3.9% lower", "Lower end-to-end tail latency."],
        ["Requests/sec", "0.544", "0.563", "Ax +3.5%", "More completed requests per second."],
        ["Output tok/s", "182.13", "187.59", "Ax +3.0%", "Higher aggregate generation rate."],
    ]
    for row, row_values in zip(summary.rows[1:], summary_values):
        for cell, value in zip(row.cells, row_values):
            set_cell_text(cell, value)

    note = next((p for p in doc.paragraphs if p.text.startswith("Imported 14B saturation results:")), None)
    if note is None:
        note = doc.add_paragraph()
    set_note(
        note,
        "Imported 14B saturation results: all six runs completed 64/64 streamed requests with cache disabled. Across three matched pairs, E6 Ax.192 had lower p95 TTFT and p95 latency in every pair, with 186.70–187.64 output tok/s versus 181.66–183.17 on E6.256. This is a small, consistent serving advantage under this controlled eight-way workload; it does not establish a general hardware cause.",
    )


def main() -> None:
    doc = Document(DOCX_PATH)
    input_index, input_table = find_bm04_input_table(doc)
    actual_values = {
        "Worker threads": "Trials 1–3: generation 32; prefill 32. Trial 4: generation 192; prefill 192. llama-bench used -t matching the selected thread count.",
        "Engine and model": "llama.cpp; Qwen2.5 7B Instruct Q4_K_M GGUF",
        "Benchmark preset": "Bare metal native prompt and decode",
        "Benchmark method": "llama-bench native microbenchmark",
        "Representative input": "Trials 1–3: Throughput comparison prompts; six prompts; 24 representative tokens. Trial 4: 24 long unique prompts; 1,483 requested prompt tokens.",
        "Run values": "Five repetitions; generation length 512; matched pair run on both shapes.",
        "Repetitions": "Four successful matched pairs imported; each side ran five native repetitions.",
    }
    for row in input_table.rows[1:]:
        field = row.cells[0].text
        if field in actual_values:
            set_cell_text(row.cells[2], actual_values[field])

    results = [
        ["1", "BM E6.256", "5 / 5", "219.00", "52.38", "24 input tokens", "Native; no HTTP TTFT"],
        ["1", "BM E6 Ax.192", "5 / 5", "219.98", "50.31", "24 input tokens", "Native; no HTTP TTFT"],
        ["2", "BM E6.256", "5 / 5", "219.92", "53.41", "24 input tokens", "Native; no HTTP TTFT"],
        ["2", "BM E6 Ax.192", "5 / 5", "219.62", "53.23", "24 input tokens", "Native; no HTTP TTFT"],
        ["3", "BM E6.256", "5 / 5", "219.58", "52.83", "24 input tokens", "Native; no HTTP TTFT"],
        ["3", "BM E6 Ax.192", "5 / 5", "220.56", "55.87", "24 input tokens", "Native; no HTTP TTFT"],
        ["4", "BM E6.256", "5 / 5", "859.26", "50.90", "1,483 input tokens", "Native; 192/192 threads; no HTTP TTFT"],
        ["4", "BM E6 Ax.192", "5 / 5", "899.28", "52.05", "1,483 input tokens", "Native; 192/192 threads; no HTTP TTFT"],
    ]
    results_table = find_bm04_results_table(doc, input_index)
    while len(results_table.rows) < len(results) + 1:
        results_table.add_row()
    if len(results_table.rows) != len(results) + 1:
        raise RuntimeError("BM 04 result table has an unexpected number of rows")
    for row, values in zip(results_table.rows[1:], results):
        for cell, value in zip(row.cells, values):
            set_cell_text(cell, value)

    bm04_heading = next(i for i, p in enumerate(doc.paragraphs) if p.text == "BM 04 Native Prompt and Decode")
    for paragraph in doc.paragraphs[bm04_heading + 1 :]:
        if paragraph.style.name == "Heading 1":
            break
        if paragraph.text in {"Results to fill", "Imported results"}:
            paragraph.text = "Imported results"
            break

    note = next(
        (
            p
            for p in doc.paragraphs
            if "Prompt tok/s is the native prefill indicator" in p.text
            or p.text.startswith("Three matched native pairs were imported from 9 September 2026.")
            or p.text.startswith("Four matched native pairs were imported from 9 September 2026.")
            or p.text.startswith("Trial 4 used 192/192 threads")
        ),
        None,
    )
    if note is None:
        raise RuntimeError("BM 04 explanatory note was not found")
    set_note(
        note,
        "Trial 4 used 192/192 threads and 1,483 requested prompt tokens. E6 Ax.192 reached 899.28 prompt tok/s and 52.05 decode tok/s, versus 859.26 and 50.90 on E6.256 (+4.7% prompt; +2.3% decode). This is native engine work, not HTTP TTFT.",
    )
    restore_bm02_results(doc)
    import_bm03_thread_sweep(doc)
    import_bm05_decode(doc)
    import_bm06_saturation(doc)
    import_bm07_larger_model(doc)
    import_bm08_larger_model_saturation(doc)
    doc.save(DOCX_PATH)


if __name__ == "__main__":
    main()
