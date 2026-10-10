"""Which Gemini models still have free quota? python -m scripts.diag_models"""

import os

from dotenv import load_dotenv

load_dotenv()
from google import genai  # noqa: E402

c = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
for m in ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-flash-latest", "gemini-flash-lite-latest",
          "gemini-3-flash-preview", "gemini-2.5-pro"]:
    try:
        r = c.models.generate_content(model=m, contents="Reply with the word OK.")
        print(f"{m:28} AVAILABLE ({(r.text or '').strip()[:10]})")
    except Exception as e:
        s = str(e)
        tag = "quota exhausted" if "429" in s else ("not found" if "404" in s else s[:90].replace("\n", " "))
        print(f"{m:28} {tag}")
