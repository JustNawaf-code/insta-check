#!/usr/bin/env python3
import requests
import re
import sys

URL_STEP1 = "https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/searchApplicationOnlineIndex.faces"
URL_STEP2 = "https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/applicationOnlineIndex.faces"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

national_id = sys.argv[1] if len(sys.argv) > 1 else "1143697983"
session = requests.Session()
session.headers.update(HEADERS)

# Step 1: GET first page to establish session
r1 = session.get(URL_STEP1, timeout=30)
print(f"Step 1 status: {r1.status_code}")
print(f"Cookies: {dict(session.cookies)}")

# Step 2: GET second page directly with same session
r2 = session.get(URL_STEP2, timeout=30)
print(f"\nStep 2 status: {r2.status_code}")
print(f"Step 2 URL: {r2.url}")
with open("debug_step2.html", "w", encoding="utf-8") as f:
    f.write(r2.text)

# Extract ViewState
vs = re.search(r'<input[^>]*name="(?:javax|jakarta)\.faces\.ViewState"[^>]*value="([^"]*)"', r2.text, re.I)
view_state = vs.group(1) if vs else "NOT FOUND"
print(f"ViewState: {view_state[:80] if view_state != 'NOT FOUND' else view_state}...")

# Check if we're on the right page (contains application form fields)
print("\n=== Check page content ===")
for pat in ["تعديل طلب القبول", "الاسم الأول", "رقم الهوية", "myForm:fnames", "myForm:capabilities", "myForm:retriveQiyasAPIData", "قدرات", "تحصيلي"]:
    found = pat in r2.text
    print(f"  '{pat}': {'FOUND' if found else 'NOT FOUND'}")

# Step 3: POST with national ID + trigger Qiyas data retrieval
print(f"\n--- Triggering Qiyas data retrieval for ID: {national_id} ---")
form_data = {
    "javax.faces.ViewState": view_state,
    "myForm": "myForm",
    "myForm:nationalNo": national_id,
    "myForm:retriveQiyasAPIData": "myForm:retriveQiyasAPIData",
}
r3 = session.post(URL_STEP2, data=form_data, timeout=30)
print(f"Step 3 status: {r3.status_code}")
print(f"Step 3 URL: {r3.url}")
with open("debug_step3.html", "w", encoding="utf-8") as f:
    f.write(r3.text)

print("\n=== Field values in response ===")
for pat in ["myForm:fnames", "myForm:fatherNames", "myForm:grandNames", "myForm:familyNames", "myForm:capabilities", "myForm:tahselMark"]:
    m = re.search(r'<input[^>]*(?:id|name)="' + re.escape(pat) + r'"[^>]*value="([^"]*)"', r3.text, re.I)
    val = m.group(1) if m else "NOT FOUND"
    print(f"  {pat}: '{val}'")

print(f"\nResponse size: {len(r3.text)} chars")
