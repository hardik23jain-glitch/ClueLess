"""What exactly is Gemini's 429? Sends a tiny text-only request. python -m scripts.diag_quota"""

import os
import re

from dotenv import load_dotenv

load_dotenv()
from google import genai  # noqa: E402

c = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
try:
    r = c.models.generate_content(model=os.getenv("LANDGUARD_GEMINI_MODEL", "gemini-2.5-flash"), contents="Reply with the word OK.")
    print("OK, request succeeded:", (r.text or "").strip())
except Exception as e:
    s = str(e)
    print(s[:1500])
    print("\n--- quota hints ---")
    for m in re.findall(r"(PerDay|PerMinute|per day|per minute|RetryInfo|retryDelay['\": ]+[\w.]+|limit: \d+|quotaMetric['\": ]+[\w./]+)", s):
        print(m)
