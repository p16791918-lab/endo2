"""
4-Agent Exam Prep System (Claude Code CLI 기반, API 키 불필요)
Usage: python exam_prep_agents.py [date]
  date: YYYY-MM-DD, MM/DD, 또는 M월D일 (default: 2023-10-23)

에이전트 구성:
  Agent 1 (직접): 시간표 파싱
  Agent 2 (claude CLI): 정리족 분석  ─┐
  Agent 3 (claude CLI): 출족 분석    ─┤ 병렬 실행
  Agent 4 (claude CLI): 강의록 분석 ─┘
"""

import os
import sys
import re
import subprocess
import concurrent.futures
from datetime import datetime, date

import openpyxl

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = "/home/user/endo2"
TIMETABLE_FILE = os.path.join(BASE_DIR, "2023학년도 1학년 2학기 시간표(안)_231005_공지용.xlsx")
JUNGRI_PDF = os.path.join(BASE_DIR, "[정리족]내분비학 1차 정리족(2).pdf")
CHUL_PDF = os.path.join(BASE_DIR, "[출족]내분비학 1차 출족(2).pdf")

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

TIMETABLE_SECTIONS = [
    (3, 4, 12),
    (14, 15, 23),
    (25, 26, 34),
]

# ---------------------------------------------------------------------------
# Agent 1: 시간표 파싱 (직접 Python으로 처리)
# ---------------------------------------------------------------------------

def agent_timetable(date_str: str) -> dict:
    print(f"[Agent 1] 시간표 파싱 중... ({date_str})")

    date_str = date_str.strip()
    target: date | None = None

    for fmt in ("%Y-%m-%d", "%m/%d", "%Y/%m/%d"):
        try:
            target = datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            pass

    if target is None:
        m = re.match(r"(\d{1,2})월\s*(\d{1,2})일", date_str)
        if m:
            target = date(2023, int(m.group(1)), int(m.group(2)))

    if target is None:
        return {"error": f"날짜 형식을 인식할 수 없습니다: {date_str}"}

    wb = openpyxl.load_workbook(TIMETABLE_FILE, data_only=True)
    ws = wb.active

    for section in TIMETABLE_SECTIONS:
        date_row, first_row, last_row = section
        for col in range(1, 50):
            cell = ws.cell(row=date_row, column=col).value
            if isinstance(cell, datetime):
                cell_date = cell.date()
            elif isinstance(cell, date):
                cell_date = cell
            else:
                continue
            if cell_date == target:
                classes = []
                for i, row in enumerate(range(first_row, last_row + 1), 1):
                    v = ws.cell(row=row, column=col).value
                    if v and str(v).strip():
                        classes.append({"period": i, "subject": str(v).strip()})
                result = {
                    "date": target.strftime("%Y-%m-%d"),
                    "weekday": WEEKDAY_KR[target.weekday()],
                    "classes": classes,
                }
                print(f"[Agent 1] 완료. 수업 {len(classes)}개 발견.")
                return result

    return {"error": f"{date_str}에 해당하는 날짜를 시간표에서 찾을 수 없습니다."}


# ---------------------------------------------------------------------------
# Claude CLI 실행 헬퍼
# ---------------------------------------------------------------------------

def run_claude(prompt: str, agent_name: str, timeout: int = 600) -> str:
    """claude -p 로 서브에이전트를 실행하고 결과를 반환한다."""
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                prompt,
                "--allowedTools", "Bash,Read",
                "--output-format", "text",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE_DIR,
        )
        if result.returncode != 0:
            err = result.stderr[:300] if result.stderr else "(오류 메시지 없음)"
            return f"[{agent_name} 오류] {err}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"[{agent_name} 오류] 타임아웃 ({timeout}초)"
    except FileNotFoundError:
        return f"[{agent_name} 오류] claude CLI를 찾을 수 없습니다. Claude Code가 설치되어 있는지 확인하세요."


# ---------------------------------------------------------------------------
# Agent 2: 정리족
# ---------------------------------------------------------------------------

def agent_jungri(classes: list[dict]) -> str:
    subjects = "\n".join(f"- {c['subject']}" for c in classes)

    prompt = f"""당신은 의과대학 시험 대비 정리족 분석 전문가입니다.

아래 수업들의 내용을 정리족 PDF에서 찾아 상세히 정리하세요.

[수업 목록]
{subjects}

[정리족 파일]
{JUNGRI_PDF}

[작업 순서]
1. Bash 도구로 PDF를 텍스트로 변환하세요:
   pdftotext -layout "{JUNGRI_PDF}" /tmp/jungri.txt
2. Bash로 목차를 확인하세요:
   head -n 200 /tmp/jungri.txt
3. 각 수업별로 Bash grep 또는 Read로 섹션을 찾아 내용을 읽으세요.
4. 아래 형식으로 각 수업을 정리하세요:

## [수업명]
### 핵심 개념
### ⭐ 교수 강조 내용 (P 표시)
### 📌 기출 출제 내용 (出 표시)
### 암기 포인트

내용이 길어도 좋으니 최대한 상세하게 작성하세요."""

    return run_claude(prompt, "정리족 Agent")


# ---------------------------------------------------------------------------
# Agent 3: 출족
# ---------------------------------------------------------------------------

def agent_chul(classes: list[dict]) -> str:
    subjects = "\n".join(f"- {c['subject']}" for c in classes)

    prompt = f"""당신은 의과대학 기출문제 분석 전문가입니다.

아래 수업들의 기출문제를 출족 PDF에서 찾아 분석하세요.

[수업 목록]
{subjects}

[출족 파일]
{CHUL_PDF}

[작업 순서]
1. Bash 도구로 PDF를 텍스트로 변환하세요:
   pdftotext -layout "{CHUL_PDF}" /tmp/chul.txt
2. Bash로 목차를 확인하세요:
   head -n 200 /tmp/chul.txt
3. 각 수업별로 기출문제 섹션을 찾아 읽으세요.
4. 아래 형식으로 정리하세요:

## [수업명]
### 기출문제 (최신순)
[연도] 문제 / 정답 / 해설
### 출제 경향 분석
### 반복 출제 포인트

문제와 해설을 모두 포함하고 최대한 많은 문제를 수록하세요."""

    return run_claude(prompt, "출족 Agent")


# ---------------------------------------------------------------------------
# Agent 4: 강의록
# ---------------------------------------------------------------------------

def agent_gangeui(classes: list[dict]) -> str:
    subjects = "\n".join(f"- {c['subject']}" for c in classes)

    # 정리족/출족 제외한 강의 파일 목록
    excluded = {os.path.basename(JUNGRI_PDF), os.path.basename(CHUL_PDF)}
    lecture_files = [
        os.path.join(BASE_DIR, f)
        for f in os.listdir(BASE_DIR)
        if (f.endswith(".pdf") or f.endswith(".pptx")) and f not in excluded
    ]
    files_str = "\n".join(f"- {f}" for f in lecture_files) if lecture_files else "없음"

    prompt = f"""당신은 의과대학 강의록 분석 전문가입니다.

아래 수업들과 관련된 강의 파일을 읽고 핵심 내용을 정리하세요.

[수업 목록]
{subjects}

[이용 가능한 강의 파일]
{files_str}

[작업 순서]
1. 수업명과 관련된 강의 파일을 찾으세요.
2. PDF 파일은 Bash로 읽으세요:
   pdftotext -layout "파일경로" -
3. 강의록에서 중요한 내용, 교수님이 강조한 부분, 임상 예시를 정리하세요.
4. 정리족/출족에서 다루지 않은 추가 내용도 포함하세요.
5. 강의 파일이 없는 수업은 명시하세요.

각 수업별로 구조화하여 정리하세요."""

    return run_claude(prompt, "강의록 Agent")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_exam_prep(date_str: str) -> None:
    print(f"\n{'='*60}")
    print(f"  시험 대비 에이전트 시작: {date_str}")
    print(f"{'='*60}\n")

    # Agent 1: 시간표 파싱
    timetable = agent_timetable(date_str)

    if "error" in timetable:
        print(f"오류: {timetable['error']}")
        return

    classes = timetable.get("classes", [])
    if not classes:
        print(f"{date_str}에 수업이 없습니다.")
        return

    print(f"\n[{timetable['date']} ({timetable['weekday']}요일)] 수업 목록:")
    for c in classes:
        print(f"  {c['period']}교시: {c['subject']}")
    print()

    # Agent 2, 3, 4: 병렬 실행
    print("에이전트 병렬 실행 중 (정리족 / 출족 / 강의록)...\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_jungri = executor.submit(agent_jungri, classes)
        future_chul = executor.submit(agent_chul, classes)
        future_gangeui = executor.submit(agent_gangeui, classes)

        jungri_result = future_jungri.result()
        print("[Agent 2] 정리족 완료.")
        chul_result = future_chul.result()
        print("[Agent 3] 출족 완료.")
        gangeui_result = future_gangeui.result()
        print("[Agent 4] 강의록 완료.")

    # 결과 저장
    safe_date = date_str.replace("/", "-").replace(" ", "_")
    output_path = os.path.join(BASE_DIR, f"exam_prep_{safe_date}.md")

    subjects_md = "\n".join(
        f"- {c['period']}교시: {c['subject']}" for c in classes
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {timetable['date']} ({timetable['weekday']}요일) 시험 대비\n\n")
        f.write(f"## 수업 목록\n\n{subjects_md}\n\n")
        f.write(f"---\n\n## 정리족 요약\n\n{jungri_result}\n\n")
        f.write(f"---\n\n## 출족 분석\n\n{chul_result}\n\n")
        f.write(f"---\n\n## 강의록 보충\n\n{gangeui_result}\n")

    print(f"\n{'='*60}")
    print(f"  결과 저장 완료: {output_path}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else "2023-10-23"
    run_exam_prep(target_date)
