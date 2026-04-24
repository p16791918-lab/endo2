"""
4-Agent Exam Prep System
Usage: python exam_prep_agents.py [date]
  date: YYYY-MM-DD, MM/DD, or M월D일 (default: 2023-10-23)
"""

import os
import sys
import json
import glob
import subprocess
import re
from datetime import datetime, date

import anthropic
import openpyxl
from pptx import Presentation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = "/home/user/endo2"
TIMETABLE_FILE = os.path.join(BASE_DIR, "2023학년도 1학년 2학기 시간표(안)_231005_공지용.xlsx")
JUNGRI_PDF = os.path.join(BASE_DIR, "[정리족]내분비학 1차 정리족(2).pdf")
CHUL_PDF = os.path.join(BASE_DIR, "[출족]내분비학 1차 출족(2).pdf")
MODEL = "claude-sonnet-4-6"

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

# Section definitions: (date_row, first_time_row, last_time_row)
# Rows are 1-indexed as in openpyxl
TIMETABLE_SECTIONS = [
    (3, 4, 12),
    (14, 15, 23),
    (25, 26, 34),
]

# ---------------------------------------------------------------------------
# PDF text cache
# ---------------------------------------------------------------------------

_pdf_cache: dict[str, list[str]] = {}


def _get_pdf_lines(pdf_file: str) -> list[str]:
    if pdf_file not in _pdf_cache:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_file, "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        _pdf_cache[pdf_file] = result.stdout.splitlines()
    return _pdf_cache[pdf_file]


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def read_timetable_for_date(date_str: str) -> dict:
    """Parse date_str and return the classes scheduled for that date."""
    # Parse the date string
    target: date | None = None
    date_str = date_str.strip()

    for fmt in ("%Y-%m-%d", "%m/%d", "%Y/%m/%d"):
        try:
            target = datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            pass

    if target is None:
        # Try Korean format: M월 D일 or M월D일
        m = re.match(r"(\d{1,2})월\s*(\d{1,2})일", date_str)
        if m:
            target = date(2023, int(m.group(1)), int(m.group(2)))

    if target is None:
        return {"error": f"날짜 형식을 인식할 수 없습니다: {date_str}"}

    wb = openpyxl.load_workbook(TIMETABLE_FILE, data_only=True)
    ws = wb.active

    found_col = None
    found_section = None

    for section in TIMETABLE_SECTIONS:
        date_row, first_time_row, last_time_row = section
        for col in range(1, 50):
            cell_val = ws.cell(row=date_row, column=col).value
            if isinstance(cell_val, datetime):
                cell_date = cell_val.date()
            elif isinstance(cell_val, date):
                cell_date = cell_val
            else:
                continue
            if cell_date == target:
                found_col = col
                found_section = section
                break
        if found_col is not None:
            break

    if found_col is None:
        return {"error": f"{date_str}에 해당하는 날짜를 시간표에서 찾을 수 없습니다."}

    date_row, first_time_row, last_time_row = found_section
    weekday = WEEKDAY_KR[target.weekday()]
    classes = []
    period = 1
    for row in range(first_time_row, last_time_row + 1):
        cell_val = ws.cell(row=row, column=found_col).value
        if cell_val and str(cell_val).strip():
            classes.append({"period": period, "subject": str(cell_val).strip()})
        period += 1

    return {
        "date": target.strftime("%Y-%m-%d"),
        "weekday": weekday,
        "classes": classes,
    }


def get_pdf_toc(pdf_file: str, num_lines: int = 150) -> str:
    """Return the first num_lines lines of a PDF with line numbers (for TOC)."""
    lines = _get_pdf_lines(pdf_file)
    result = []
    for i, line in enumerate(lines[:num_lines], start=1):
        result.append(f"{i:5d}: {line}")
    return "\n".join(result)


def search_pdf_for_keyword(pdf_file: str, keyword: str, context_lines: int = 5) -> str:
    """Search PDF text for keyword, return matches with surrounding context."""
    lines = _get_pdf_lines(pdf_file)
    results = []
    for i, line in enumerate(lines):
        if keyword in line:
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            block = []
            for j in range(start, end):
                marker = ">>>" if j == i else "   "
                block.append(f"{marker} {j+1:5d}: {lines[j]}")
            results.append("\n".join(block))
    if not results:
        return f"키워드 '{keyword}'를 찾을 수 없습니다."
    return f"\n{'='*60}\n".join(results)


def read_pdf_lines(pdf_file: str, start_line: int, end_line: int) -> str:
    """Return specific line range from PDF text with line numbers."""
    lines = _get_pdf_lines(pdf_file)
    total = len(lines)
    s = max(1, start_line) - 1
    e = min(total, end_line)
    result = []
    for i in range(s, e):
        result.append(f"{i+1:5d}: {lines[i]}")
    return "\n".join(result)


def list_lecture_files() -> list[str]:
    """List lecture PPTX and PDF files (excluding 정리족/출족 PDFs)."""
    excluded = {JUNGRI_PDF, CHUL_PDF}
    files = []
    for pattern in ["*.pptx", "*.pdf"]:
        for f in glob.glob(os.path.join(BASE_DIR, pattern)):
            if f not in excluded:
                files.append(f)
    return files


def read_pptx_file(file_path: str) -> str:
    """Extract text from a PPTX file."""
    try:
        prs = Presentation(file_path)
    except Exception as e:
        return f"PPTX 읽기 오류: {e}"
    parts = []
    for i, slide in enumerate(prs.slides, start=1):
        slide_texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    slide_texts.append(text)
        if slide_texts:
            parts.append(f"--- 슬라이드 {i} ---\n" + "\n".join(slide_texts))
    return "\n\n".join(parts) if parts else "(내용 없음)"


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic API format)
# ---------------------------------------------------------------------------

TOOL_READ_TIMETABLE = {
    "name": "read_timetable_for_date",
    "description": "주어진 날짜의 시간표를 읽어 수업 목록을 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "date_str": {
                "type": "string",
                "description": "날짜 (YYYY-MM-DD, MM/DD, 또는 M월D일 형식)",
            }
        },
        "required": ["date_str"],
    },
}

TOOL_GET_PDF_TOC = {
    "name": "get_pdf_toc",
    "description": "PDF 파일의 목차 부분(앞부분)을 읽습니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pdf_file": {"type": "string", "description": "PDF 파일 경로"},
            "num_lines": {
                "type": "integer",
                "description": "읽을 줄 수 (기본 150)",
                "default": 150,
            },
        },
        "required": ["pdf_file"],
    },
}

TOOL_SEARCH_PDF = {
    "name": "search_pdf_for_keyword",
    "description": "PDF에서 키워드를 검색하고 주변 문맥을 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pdf_file": {"type": "string", "description": "PDF 파일 경로"},
            "keyword": {"type": "string", "description": "검색할 키워드"},
            "context_lines": {
                "type": "integer",
                "description": "키워드 앞뒤로 포함할 줄 수 (기본 5)",
                "default": 5,
            },
        },
        "required": ["pdf_file", "keyword"],
    },
}

TOOL_READ_PDF_LINES = {
    "name": "read_pdf_lines",
    "description": "PDF의 특정 줄 범위를 읽습니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pdf_file": {"type": "string", "description": "PDF 파일 경로"},
            "start_line": {"type": "integer", "description": "시작 줄 번호"},
            "end_line": {"type": "integer", "description": "끝 줄 번호"},
        },
        "required": ["pdf_file", "start_line", "end_line"],
    },
}

TOOL_LIST_LECTURE_FILES = {
    "name": "list_lecture_files",
    "description": "강의록 파일 목록을 반환합니다 (pptx, pdf).",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

TOOL_READ_PPTX = {
    "name": "read_pptx_file",
    "description": "PPTX 강의 파일에서 텍스트를 추출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "PPTX 파일 경로"}
        },
        "required": ["file_path"],
    },
}

ALL_TOOL_FUNCTIONS = {
    "read_timetable_for_date": read_timetable_for_date,
    "get_pdf_toc": get_pdf_toc,
    "search_pdf_for_keyword": search_pdf_for_keyword,
    "read_pdf_lines": read_pdf_lines,
    "list_lecture_files": list_lecture_files,
    "read_pptx_file": read_pptx_file,
}

# ---------------------------------------------------------------------------
# Generic agent runner (manual tool-use loop)
# ---------------------------------------------------------------------------

def run_agent(
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    tool_functions: dict,
    max_iterations: int = 20,
) -> str:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_message}]

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=8096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # Convert response content to serializable list for messages history
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            return "\n".join(
                block.text for block in response.content if block.type == "text"
            )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    fn = tool_functions.get(block.name)
                    if fn is None:
                        result_content = f"알 수 없는 도구: {block.name}"
                    else:
                        try:
                            raw = fn(**block.input)
                            result_content = json.dumps(raw, ensure_ascii=False) if isinstance(raw, (dict, list)) else str(raw)
                        except Exception as e:
                            result_content = f"도구 실행 오류: {e}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_content,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "에이전트가 최대 반복 횟수 내에 완료하지 못했습니다."


# ---------------------------------------------------------------------------
# Agent 1: Timetable
# ---------------------------------------------------------------------------

def agent_timetable(date_str: str) -> dict:
    print(f"[Agent 1] 시간표 에이전트 실행 중... ({date_str})")

    system = (
        "당신은 시간표 에이전트입니다. "
        "주어진 날짜의 시간표를 읽어 그날 수업 목록을 정확히 파악하세요. "
        "read_timetable_for_date 도구를 사용하여 결과를 가져오고, "
        "결과를 JSON 형식 그대로 반환하세요."
    )

    user_msg = f"날짜 {date_str}의 수업 목록을 알려주세요."

    result_text = run_agent(
        system_prompt=system,
        user_message=user_msg,
        tools=[TOOL_READ_TIMETABLE],
        tool_functions={"read_timetable_for_date": read_timetable_for_date},
        max_iterations=5,
    )

    # Also call directly to get the structured dict
    timetable_data = read_timetable_for_date(date_str)
    print(f"[Agent 1] 완료. 수업 {len(timetable_data.get('classes', []))}개 발견.")
    return timetable_data


# ---------------------------------------------------------------------------
# Agent 2: 정리족
# ---------------------------------------------------------------------------

def agent_jungri(classes: list[dict]) -> str:
    print(f"[Agent 2] 정리족 에이전트 실행 중...")

    subjects = [c["subject"] for c in classes]
    subjects_str = "\n".join(f"- {s}" for s in subjects)

    system = (
        "당신은 정리족 에이전트입니다. 의과대학 시험 준비를 도와주는 전문가입니다.\n"
        "주어진 수업들에 대해 정리족 PDF에서 해당 섹션을 찾아 꼼꼼히 읽고 정리하세요.\n\n"
        "작업 순서:\n"
        "1. get_pdf_toc 도구로 목차를 읽어 각 수업의 시작 페이지/줄을 파악하세요.\n"
        "2. search_pdf_for_keyword 도구로 수업명을 검색하여 섹션 위치를 확인하세요.\n"
        "3. read_pdf_lines 도구로 각 수업 섹션을 충분히 읽으세요 (한 번에 200줄씩).\n"
        "4. 각 수업별로 다음을 정리하세요:\n"
        "   - 핵심 개념 및 내용 요약\n"
        "   - 'P' 표시된 교수 강조 내용 (⭐ 표시)\n"
        "   - '出' 표시된 기출 출제 내용 (📌 표시)\n"
        "   - 암기 포인트\n\n"
        f"정리족 파일 경로: {JUNGRI_PDF}\n\n"
        "내용이 길어도 좋으니 최대한 많은 내용을 포함하세요."
    )

    user_msg = (
        f"다음 수업들의 정리족 내용을 찾아 정리해주세요:\n\n{subjects_str}\n\n"
        "각 수업별로 목차에서 위치를 찾고, 해당 섹션 전체를 읽어 상세히 정리하세요."
    )

    result = run_agent(
        system_prompt=system,
        user_message=user_msg,
        tools=[TOOL_GET_PDF_TOC, TOOL_SEARCH_PDF, TOOL_READ_PDF_LINES],
        tool_functions={
            "get_pdf_toc": get_pdf_toc,
            "search_pdf_for_keyword": search_pdf_for_keyword,
            "read_pdf_lines": read_pdf_lines,
        },
        max_iterations=30,
    )

    print(f"[Agent 2] 완료.")
    return result


# ---------------------------------------------------------------------------
# Agent 3: 출족
# ---------------------------------------------------------------------------

def agent_chul(classes: list[dict]) -> str:
    print(f"[Agent 3] 출족 에이전트 실행 중...")

    subjects = [c["subject"] for c in classes]
    subjects_str = "\n".join(f"- {s}" for s in subjects)

    system = (
        "당신은 출족 에이전트입니다. 의과대학 기출문제 분석 전문가입니다.\n"
        "주어진 수업들에 대해 출족 PDF에서 해당 문제들을 찾아 분석하고 정리하세요.\n\n"
        "작업 순서:\n"
        "1. get_pdf_toc 도구로 목차를 읽어 각 수업의 시작 위치를 파악하세요.\n"
        "2. search_pdf_for_keyword 도구로 수업명을 검색하여 섹션 위치를 확인하세요.\n"
        "3. read_pdf_lines 도구로 각 수업 섹션의 문제들을 읽으세요.\n"
        "4. 각 수업별로 다음을 정리하세요:\n"
        "   - 최근 년도(최신순) 기출문제 목록과 해설\n"
        "   - 출제 경향 분석 (자주 나오는 주제, 문제 유형)\n"
        "   - 반복 출제 포인트 (出을 타는 내용)\n"
        "   - 교수님이 바뀐 경우 최근 경향 위주로 정리\n\n"
        f"출족 파일 경로: {CHUL_PDF}\n\n"
        "문제와 해설이 함께 있으니 모두 포함하여 정리하세요. "
        "내용이 길어도 좋으니 최대한 많은 문제를 포함하세요."
    )

    user_msg = (
        f"다음 수업들의 기출문제를 찾아 정리해주세요:\n\n{subjects_str}\n\n"
        "각 수업별로 목차에서 위치를 찾고, 문제와 해설을 모두 정리하며 출제 경향을 분석하세요."
    )

    result = run_agent(
        system_prompt=system,
        user_message=user_msg,
        tools=[TOOL_GET_PDF_TOC, TOOL_SEARCH_PDF, TOOL_READ_PDF_LINES],
        tool_functions={
            "get_pdf_toc": get_pdf_toc,
            "search_pdf_for_keyword": search_pdf_for_keyword,
            "read_pdf_lines": read_pdf_lines,
        },
        max_iterations=30,
    )

    print(f"[Agent 3] 완료.")
    return result


# ---------------------------------------------------------------------------
# Agent 4: 강의록
# ---------------------------------------------------------------------------

def agent_gangeui(classes: list[dict], jungri_summary: str, chul_summary: str) -> str:
    print(f"[Agent 4] 강의록 에이전트 실행 중...")

    subjects = [c["subject"] for c in classes]
    subjects_str = "\n".join(f"- {s}" for s in subjects)

    system = (
        "당신은 강의록 에이전트입니다. 교수님의 강의 자료에서 중요한 내용을 찾는 전문가입니다.\n"
        "주어진 수업들의 강의 파일을 읽고, 정리족과 출족에서 강조된 내용을 보충 정리하세요.\n\n"
        "작업 순서:\n"
        "1. list_lecture_files 도구로 이용 가능한 강의 파일 목록을 확인하세요.\n"
        "2. 수업명과 관련된 강의 파일을 read_pptx_file 도구로 읽으세요.\n"
        "3. 정리족 요약의 ⭐(교수 강조) 및 📌(기출) 내용과 관련된 부분을 강의록에서 찾으세요.\n"
        "4. 출족 요약의 자주 출제되는 내용을 강의록에서 확인하고 보충 설명을 추가하세요.\n"
        "5. 각 수업별로 강의록에서 발견한 추가 중요 내용을 정리하세요.\n\n"
        "강의 파일이 없거나 관련 내용을 찾기 어려운 경우 해당 사항을 명시하세요."
    )

    # Truncate summaries if very long to stay within context
    jungri_excerpt = jungri_summary[:3000] + "...(이하 생략)" if len(jungri_summary) > 3000 else jungri_summary
    chul_excerpt = chul_summary[:3000] + "...(이하 생략)" if len(chul_summary) > 3000 else chul_summary

    user_msg = (
        f"다음 수업들의 강의록을 읽고 중요 내용을 보충 정리해주세요:\n\n{subjects_str}\n\n"
        f"=== 정리족 요약 (참고용) ===\n{jungri_excerpt}\n\n"
        f"=== 출족 요약 (참고용) ===\n{chul_excerpt}\n\n"
        "강의 파일에서 위의 강조 내용들을 찾아 보충 설명을 추가하고, "
        "강의록에서만 발견되는 추가 중요 내용도 정리하세요."
    )

    result = run_agent(
        system_prompt=system,
        user_message=user_msg,
        tools=[TOOL_LIST_LECTURE_FILES, TOOL_READ_PPTX, TOOL_GET_PDF_TOC, TOOL_SEARCH_PDF, TOOL_READ_PDF_LINES],
        tool_functions={
            "list_lecture_files": list_lecture_files,
            "read_pptx_file": read_pptx_file,
            "get_pdf_toc": get_pdf_toc,
            "search_pdf_for_keyword": search_pdf_for_keyword,
            "read_pdf_lines": read_pdf_lines,
        },
        max_iterations=20,
    )

    print(f"[Agent 4] 완료.")
    return result


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_exam_prep(date_str: str) -> None:
    print(f"\n{'='*60}")
    print(f"  시험 대비 에이전트 시작: {date_str}")
    print(f"{'='*60}\n")

    # Agent 1: Get timetable
    timetable_data = agent_timetable(date_str)

    if "error" in timetable_data:
        print(f"오류: {timetable_data['error']}")
        return

    classes = timetable_data.get("classes", [])
    if not classes:
        print(f"{date_str}에 수업이 없습니다.")
        return

    print(f"\n[{timetable_data['date']} ({timetable_data['weekday']}요일)] 수업 목록:")
    for c in classes:
        print(f"  {c['period']}교시: {c['subject']}")
    print()

    # Agent 2: 정리족
    jungri_result = agent_jungri(classes)

    # Agent 3: 출족
    chul_result = agent_chul(classes)

    # Agent 4: 강의록
    gangeui_result = agent_gangeui(classes, jungri_result, chul_result)

    # Save output
    safe_date = date_str.replace("/", "-").replace(" ", "_")
    output_path = os.path.join(BASE_DIR, f"exam_prep_{safe_date}.md")

    subjects_md = "\n".join(
        f"- {c['period']}교시: {c['subject']}" for c in classes
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {timetable_data['date']} ({timetable_data['weekday']}요일) 시험 대비\n\n")
        f.write(f"## 수업 목록\n\n{subjects_md}\n\n")
        f.write(f"---\n\n## 정리족 요약\n\n{jungri_result}\n\n")
        f.write(f"---\n\n## 출족 분석\n\n{chul_result}\n\n")
        f.write(f"---\n\n## 강의록 보충\n\n{gangeui_result}\n")

    print(f"\n{'='*60}")
    print(f"  결과 저장 완료: {output_path}")
    print(f"{'='*60}\n")

    # Also print summaries to stdout
    print("=== 정리족 요약 ===")
    print(jungri_result)
    print("\n=== 출족 분석 ===")
    print(chul_result)
    print("\n=== 강의록 보충 ===")
    print(gangeui_result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else "2023-10-23"
    run_exam_prep(target_date)
