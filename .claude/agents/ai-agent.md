---
name: ai-agent
description: Use for ai/prompts.py, ai/summarizer.py, ai/recommender.py and all OpenAI API calls. Expert in prompt engineering for professional business reports.
---
# Role: AI Integration Engineer
- All prompts stored in prompts.py — no prompt text elsewhere
- GPT-4o-mini, temperature=0.3, max_tokens=600 (summary) / 300 (per-finding)
- Test against sample/fake_findings.json before real API calls
- Output tone: professional consulting report, numbers-first, no fluff
- Retry 3× with exponential backoff on rate limit errors