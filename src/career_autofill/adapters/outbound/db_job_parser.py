import re
from datetime import datetime
from urllib.parse import urlsplit

from ...domain.models import Cell, JobRole, SourceSnapshot
from ...domain.policies import SEOUL, check_url


def expand_rows(rows: list[list[Cell]]) -> list[list[str]]:
    """Respect rowspan/colspan so later rows keep the correct qualification and location."""
    pending: dict[int, tuple[str, int]] = {}
    result = []
    for row in rows:
        occupied = {column: text for column, (text, _) in pending.items()}
        pending = {
            column: (text, count - 1) for column, (text, count) in pending.items() if count > 1
        }
        column = 0
        for cell in row:
            while column in occupied:
                column += 1
            for offset in range(cell.colspan):
                position = column + offset
                occupied[position] = cell.text.strip()
                if cell.rowspan > 1:
                    pending[position] = (cell.text.strip(), cell.rowspan - 1)
            column += cell.colspan
        result.append([occupied.get(i, "") for i in range(max(occupied, default=-1) + 1)])
    return result


def parse_deadline(text: str) -> datetime | None:
    match = re.search(
        r"마감일\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*"
        r"(?:(오후|오전)\s*)?(\d{1,2}):(\d{2})",
        text,
    )
    if not match:
        return None
    year, month, day, meridiem, hour, minute = match.groups()
    hours = int(hour)
    if meridiem == "오후" and hours < 12:
        hours += 12
    if meridiem == "오전" and hours == 12:
        hours = 0
    return datetime(int(year), int(month), int(day), hours, int(minute), tzinfo=SEOUL)


def parse_job(document: SourceSnapshot) -> list[JobRole]:
    check_url(document.url, application=True)
    if not re.fullmatch(r"/career/jobs/\d+", urlsplit(document.url).path):
        raise ValueError("A job detail URL is required.")
    company_match = re.search(r"\[([^\]]+)\]", document.title)
    company = company_match.group(1) if company_match else "DB그룹"
    general = re.search(r"응시자격\s*([\s\S]*?)(?:전형방법|채용절차)", document.text)
    result = []
    for table in document.tables:
        rows = expand_rows(table)
        header_index = next(
            (i for i, row in enumerate(rows) if "모집직무" in row and "직무내용" in row), None
        )
        if header_index is None:
            continue
        headers = rows[header_index]
        title_column = headers.index("모집직무")
        duty_column = headers.index("직무내용")
        qualification_column = headers.index("지원자격 및 우대사항")
        location_column = headers.index("지역")
        for row in rows[header_index + 1 :]:
            if len(row) <= qualification_column:
                continue
            title, duties = row[title_column], row[duty_column]
            if not title or not duties or title.startswith("*") or duties.startswith("*"):
                continue
            qualifications = row[qualification_column]
            required, _, preferred = qualifications.partition("※ 우대사항")
            result.append(
                JobRole(
                    id=f"{urlsplit(document.url).path.rsplit('/', 1)[-1]}:{len(result)}",
                    company=company,
                    title=title.replace("\n", " "),
                    responsibilities=duties,
                    qualifications=required,
                    preferred=preferred,
                    general_qualifications=general.group(1).strip() if general else "",
                    location=row[location_column] if len(row) > location_column else "",
                    source_url=document.url,
                    deadline=parse_deadline(document.text),
                    collected_at=document.collected_at,
                    career_type="신입/경력" if "신입/경력\n신입/경력" in document.text else "신입",
                )
            )
    if not result:
        raise ValueError(
            "No readable role table found. Import verified roles from visible content."
        )
    return result
