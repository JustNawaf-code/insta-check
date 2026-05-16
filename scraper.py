#!/usr/bin/env python3
import re
import sys
import requests

URL_STEP1 = "https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/searchApplicationOnlineIndex.faces"
URL_STEP2 = "https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/applicationOnlineIndex.faces"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

FIELD_PATTERNS = {
    "first_name": ["myForm:fnames"],
    "father_name": ["myForm:fatherNames"],
    "grand_name": ["myForm:grandNames"],
    "family_name": ["myForm:familyNames"],
    "capabilities": ["myForm:capabilities"],
    "tah_score": ["myForm:tahselMark"],
}


def extract_view_state(html):
    m = re.search(
        r'<input[^>]*name="(?:javax|jakarta)\.faces\.ViewState"[^>]*value="([^"]*)"',
        html, re.I
    )
    return m.group(1) if m else ""


def extract_value(html, field_names):
    for name in field_names:
        pattern = re.escape(name)
        m = re.search(
            r'<input[^>]*(?:id|name)="[^"]*' + pattern + r'[^"]*"[^>]*value="([^"]*)"',
            html, re.I
        )
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def scrape(national_id):
    session = requests.Session()
    session.headers.update(HEADERS)

    # Step 1: GET first page to establish session
    session.get(URL_STEP1, timeout=30)

    # Step 2: GET second page directly with same session
    r2 = session.get(URL_STEP2, timeout=30)
    r2.raise_for_status()
    view_state = extract_view_state(r2.text)

    # Step 3: POST with ID + trigger Qiyas data retrieval
    r3 = session.post(URL_STEP2, data={
        "javax.faces.ViewState": view_state,
        "myForm": "myForm",
        "myForm:nationalNo": national_id,
        "myForm:retriveQiyasAPIData": "myForm:retriveQiyasAPIData",
    }, timeout=30)
    r3.raise_for_status()

    result = {}
    for key, patterns in FIELD_PATTERNS.items():
        val = extract_value(r3.text, patterns)
        if val:
            result[key] = val

    name_parts = []
    for p in ["first_name", "father_name", "grand_name", "family_name"]:
        if p in result:
            name_parts.append(result[p])
    if name_parts:
        result["full_name"] = " ".join(name_parts)

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <national_id>")
        sys.exit(1)

    national_id = sys.argv[1].strip()
    print(f"\u0627\u0644\u0628\u062d\u062b \u0639\u0646 \u0631\u0642\u0645 \u0627\u0644\u0647\u0648\u064a\u0629: {national_id}")

    try:
        result = scrape(national_id)
        if not result:
            print("\u0644\u0645 \u064a\u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 \u0646\u062a\u0627\u0626\u062c")
            sys.exit(1)

        print(f"\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0643\u0627\u0645\u0644: {result.get('full_name', '-')}")
        print(f"\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0623\u0648\u0644: {result.get('first_name', '-')}")
        print(f"\u0627\u0633\u0645 \u0627\u0644\u0623\u0628: {result.get('father_name', '-')}")
        print(f"\u0627\u0633\u0645 \u0627\u0644\u062c\u062f: {result.get('grand_name', '-')}")
        print(f"\u0627\u0633\u0645 \u0627\u0644\u0639\u0627\u0626\u0644\u0629: {result.get('family_name', '-')}")
        print(f"\u062f\u0631\u062c\u0629 \u0627\u0644\u0642\u062f\u0631\u0627\u062a: {result.get('capabilities', '-')}")
        print(f"\u062f\u0631\u062c\u0629 \u0627\u0644\u062a\u062d\u0635\u064a\u0644\u064a: {result.get('tah_score', '-')}")
    except Exception as e:
        print(f"\u062e\u0637\u0623: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
