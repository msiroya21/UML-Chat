import asyncio
import logging
import re
from app.core.config import get_settings
from app.services.llm_client import invoke_with_fallback, LLMConfigError

settings = get_settings()
logger = logging.getLogger(__name__)

_STOP = {
    'a','an','the','and','or','but','for','in','on','at','to','from','with',
    'by','of','is','are','was','were','will','be','that','this','which',
    'i','you','we','they','it','my','your','our','their','its','am',
    'need','want','create','make','design','build','develop','please',
    'help','im',"i'm","i'd","i've",'me','us','them',
}

def _heuristic_title(prompt: str) -> str:
    words = re.findall(r"[a-zA-Z]+", prompt)
    kept = [w.capitalize() for w in words if w.lower() not in _STOP][:4]
    return " ".join(kept) if kept else "New Session"

def generate_session_title(prompt: str) -> str:
    try:
        response = invoke_with_fallback([
            ("system",
             "Generate a 3-5 word title for a software design session based on the user's prompt. "
             "Output ONLY the title — no quotes, no punctuation at the end, no explanation. "
             "Capitalise each word. Example output: Compliance Monitoring Platform"),
            ("user", f"Prompt (first 400 chars): {prompt[:400]}"),
        ], temperature=0.0)
        title = response.content.strip().strip('"\'')
        if 1 <= len(title.split()) <= 7:
            return title
    except LLMConfigError:
        logger.info("No LLM configured; using heuristic session title.")
    except Exception as e:
        logger.warning("Session title LLM call failed: %s", e)
    return _heuristic_title(prompt)

async def generate_session_title_async(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, generate_session_title, prompt)
