"""Day 1 connectivity checks. Run with Python 3.10 or newer."""

import argparse
import json
from functools import partial
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

PUBLIC_API = "https://apis.data.go.kr"
KST = timezone(timedelta(hours=9))
HALF_MARATHON_KM = 21.0975
HALF_DISTANCE_RANGE = (20.0, 22.0)


class ProbeError(ValueError):
    """A safe, user-facing validation error."""


def load_env():
    env_path = Path(__file__).with_name(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().partition("=")
            if separator and name and not name.startswith("#"):
                os.environ.setdefault(name.strip(), value.strip().strip("'\042"))


def request_json(url, *, params=None, payload=None, token=None):
    if params:
        url = f"{url}?{urlencode(params)}"
    headers = {}
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=body, headers=headers), timeout=20) as response:
        raw = response.read()
    try:
        return json.loads(raw)
    except ValueError:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raise ProbeError("NON_JSON_RESPONSE") from None
        code = root.findtext(".//returnReasonCode") or root.findtext(".//resultCode")
        raise ProbeError(f"NON_JSON_RESPONSE_UPSTREAM_CODE_{code if code and code.isdigit() else 'UNKNOWN'}") from None


def public_body(path, key_name, **params):
    key = os.getenv(key_name) or os.getenv("PUBLIC_DATA_KEY")
    if not key:
        raise ProbeError(f"API_KEY_MISSING ({key_name} 또는 PUBLIC_DATA_KEY)")
    response = request_json(f"{PUBLIC_API}/{path}", params={"serviceKey": key, **params})
    envelope = response["response"]
    code = str(envelope["header"]["resultCode"])
    if code not in {"0", "00", "0000"}:
        raise ProbeError(f"UPSTREAM_RESULT_CODE_{code}" if code.isdigit() else "UPSTREAM_ERROR")
    return envelope["body"]


def check_course(*, half=False):
    filters = {}
    if query := os.getenv("COURSE_QUERY"):
        filters["crsKorNm"] = query

    fields = ("crsIdx", "crsKorNm", "sigun", "crsDstnc", "gpxpath")
    page_size = 100 if half else 10
    candidates = {}
    page = 1
    found_courses = False
    while True:
        body = public_body(
            "B551011/Durunubi/courseList", "COURSE_API_KEY", _type="json",
            MobileOS="ETC", MobileApp="RunningPlannerDay1", numOfRows=page_size,
            pageNo=page, **filters,
        )
        courses = (body.get("items") or {}).get("item", [])
        if isinstance(courses, dict):
            courses = [courses]
        if not courses:
            break
        found_courses = True
        for course in courses:
            if not all(course.get(field) for field in fields):
                continue
            sample = {field: course[field] for field in fields}
            if half:
                try:
                    distance = float(course["crsDstnc"])
                except (TypeError, ValueError):
                    continue
                if not HALF_DISTANCE_RANGE[0] <= distance <= HALF_DISTANCE_RANGE[1]:
                    continue
                sample["distance_km"] = distance
            candidates[sample["crsIdx"]] = sample

        if not half:
            break
        actual_page_size = int(body.get("numOfRows") or page_size)
        total = body.get("totalCount")
        if total is None and len(courses) < actual_page_size:
            break
        if total is not None and page * actual_page_size >= int(total):
            break
        page += 1

    if not found_courses:
        raise ProbeError("NO_RESULT")
    if half:
        if not candidates:
            raise ProbeError("NO_HALF_COURSE (20~22km 및 GPX 조건의 코스 없음)")
        samples = sorted(
            candidates.values(),
            key=lambda course: abs(course["distance_km"] - HALF_MARATHON_KM),
        )
        return {
            "target_km": HALF_MARATHON_KM,
            "distance_range_km": HALF_DISTANCE_RANGE,
            "matching_courses": len(samples),
            "samples": samples[:3],
        }
    if not candidates:
        raise ProbeError("MISSING_DATA (코스 ID·이름·지역·거리·GPX)")
    return {"samples": list(candidates.values())[:3]}


def check_weather():
    now = datetime.now(KST)
    available = now - timedelta(minutes=15)
    base = available.replace(minute=0, second=0, microsecond=0)
    while base.hour not in (2, 5, 8, 11, 14, 17, 20, 23):
        base -= timedelta(hours=1)
    nx = int(os.getenv("WEATHER_NX") or 60)
    ny = int(os.getenv("WEATHER_NY") or 127)
    body = public_body(
        "1360000/VilageFcstInfoService_2.0/getVilageFcst", "WEATHER_API_KEY",
        dataType="JSON", numOfRows=1000, pageNo=1, base_date=base.strftime("%Y%m%d"),
        base_time=base.strftime("%H%M"), nx=nx, ny=ny,
    )
    slots = {}
    for item in (body.get("items") or {}).get("item", []):
        slot = f"{item['fcstDate']} {item['fcstTime']}"
        if item["category"] in {"PTY", "POP", "TMP"}:
            slots.setdefault(slot, {})[item["category"]] = item["fcstValue"]
    current_slot = now.strftime("%Y%m%d %H00")
    forecast = [
        {"forecast_at_kst": slot, **values}
        for slot, values in sorted(slots.items())
        if slot >= current_slot and all(values.get(field) not in (None, "") for field in ("PTY", "POP", "TMP"))
    ]
    if not forecast:
        raise ProbeError("MISSING_DATA (향후 예보 PTY·POP·TMP)")
    return {"grid": [nx, ny], "issued_at_kst": base.isoformat(), "forecast": forecast[:8]}


def check_air():
    now = datetime.now(KST)
    region = os.getenv("AIR_REGION") or "서울"
    pattern = rf"(?:^|,)\s*{re.escape(region)}\s*:\s*(좋음|보통|매우나쁨|매우 나쁨|나쁨)"
    forecasts = {}
    for pollutant in ("PM10", "PM25"):
        region_reports = []
        for days_ago in (0, 1):
            published_on = (now - timedelta(days=days_ago)).date().isoformat()
            body = public_body(
                "B552584/ArpltnInforInqireSvc/getMinuDustFrcstDspth", "AIR_API_KEY",
                returnType="json", searchDate=published_on, InformCode=pollutant,
            )
            for report in body.get("items") or []:
                if report.get("informCode") != pollutant:
                    continue
                grade = re.search(pattern, report.get("informGrade") or "")
                if grade and (report.get("informData") or "") >= now.date().isoformat():
                    region_reports.append({
                        "date": report["informData"],
                        "grade": grade.group(1),
                        "issued_at": report["dataTime"],
                    })
            if region_reports:
                break
        if not region_reports:
            raise ProbeError(f"MISSING_DATA ({pollutant}, 권역·예보 날짜 확인)")
        forecasts[pollutant] = region_reports
    return {"region": region, "forecasts": forecasts}


def check_llm():
    token = os.getenv("GMS_KEY") or os.getenv("OPENAI_API_KEY")
    if not token:
        raise ProbeError("API_KEY_MISSING (GMS_KEY 또는 OPENAI_API_KEY)")
    base_url = os.getenv("LLM_BASE_URL")
    if not base_url:
        raise ProbeError("LLM_BASE_URL_MISSING")
    if urlparse(base_url).scheme != "https":
        raise ProbeError("LLM_BASE_URL_MUST_USE_HTTPS")
    url = f"{base_url.rstrip('/')}/chat/completions"
    model = os.getenv("LLM_MODEL") or "gpt-5-nano"
    basic = request_json(url, token=token, payload={
        "model": model, "messages": [{"role": "user", "content": "간단히 인사해줘."}],
    })
    if not basic["choices"][0]["message"].get("content"):
        raise ProbeError("LLM_EMPTY_REPLY")
    tool = {
        "type": "function",
        "function": {
            "name": "search_courses",
            "description": "사용자가 특정 지역의 실제 러닝 코스와 거리를 요청하면 호출한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "min_km": {"type": "number"},
                    "max_km": {"type": "number"},
                },
                "required": ["area"],
            },
        },
    }
    result = request_json(url, token=token, payload={
        "model": model,
        "messages": [{"role": "user", "content": "서울에서 하프마라톤 연습용으로 20~22km 실제 러닝 코스 후보를 조회해줘."}],
        "tools": [tool],
        "tool_choice": "auto",
    })
    calls = result["choices"][0]["message"].get("tool_calls", [])
    for call in calls:
        function = call.get("function", {})
        if function.get("name") == "search_courses":
            arguments = json.loads(function["arguments"])
            if isinstance(arguments, dict) and arguments.get("area"):
                return {"basic_reply": True, "tool_selected": function["name"], "arguments": arguments}
    raise ProbeError("TOOL_NOT_SELECTED_WITH_VALID_ARGUMENTS (기본 LLM 호출은 성공)")


def main():
    checks = {"course": check_course, "weather": check_weather, "air": check_air, "llm": check_llm}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", nargs="?", choices=["all", *checks, "half"], default="all")
    selected = parser.parse_args().check
    if selected == "half":
        checks = {"half": partial(check_course, half=True)}
    load_env()
    results = {}
    for name, check in checks.items():
        if selected not in ("all", name):
            continue
        try:
            results[name] = {"ok": True, "data": check()}
        except HTTPError as error:
            results[name] = {"ok": False, "error": f"HTTP_{error.code}"}
        except (URLError, TimeoutError):
            results[name] = {"ok": False, "error": "NETWORK_ERROR"}
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            results[name] = {"ok": False, "error": "UNEXPECTED_RESPONSE_STRUCTURE"}
        except ProbeError as error:
            results[name] = {"ok": False, "error": str(error)}
        except ValueError:
            results[name] = {"ok": False, "error": "INVALID_INPUT_OR_DATA"}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(not result["ok"] for result in results.values()))


if __name__ == "__main__":
    sys.exit(main())
