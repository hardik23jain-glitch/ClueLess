"""Why is a Gemini reply cut off? Prints finish_reason and token usage. python -m scripts.diag_gemini <pdf>"""

import sys

from dotenv import load_dotenv

load_dotenv()

from google.genai import types  # noqa: E402

from extract.config import Config  # noqa: E402
from extract.ingest import load_document  # noqa: E402
from extract.preprocess import preprocess_pages  # noqa: E402
from extract.prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from extract.providers import GeminiProvider, encode_jpeg  # noqa: E402
from extract.redact import redact_pages  # noqa: E402

cfg = Config.from_env()
pages, _, _, _ = load_document(sys.argv[1], cfg)
preprocess_pages(pages, cfg)
imgs, _ = redact_pages(pages)
g = GeminiProvider(cfg)
parts = []
for i, im in enumerate(imgs, 1):
    parts += [types.Part.from_text(text=f"Page {i}:"), types.Part.from_bytes(data=encode_jpeg(im, 92), mime_type="image/jpeg")]
parts.append(types.Part.from_text(text=build_user_prompt(len(imgs))))
r = g.client.models.generate_content(
    model=g.model, contents=[types.Content(role="user", parts=parts)],
    config=types.GenerateContentConfig(temperature=0, max_output_tokens=cfg.max_output_tokens,
                                       response_mime_type="application/json", system_instruction=SYSTEM_PROMPT))
c = r.candidates[0]
print("finish_reason:", c.finish_reason)
print("usage:", r.usage_metadata)
print("reply chars:", len(r.text or ""))
