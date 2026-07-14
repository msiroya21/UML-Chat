import zlib
import base64
import string
import logging
from typing import Optional, Tuple
import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Distinctive markers PlantUML injects into an error image. Used as a backup when the
# server doesn't set the error header (user labels won't contain these exact phrases).
_ERROR_MARKERS = ("Syntax Error?", "cannot find message", "[From string (line")

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Shared PlantUML HTTP client (one connection pool for all renders/exports)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client


def encode_plantuml(plantuml_code: str) -> str:
    """Compress + custom-base64 encode PlantUML text for the server's GET API."""
    zlibbed_str = zlib.compress(plantuml_code.encode("utf-8"))
    compressed_string = zlibbed_str[2:-4]
    plantuml_alphabet = string.digits + string.ascii_uppercase + string.ascii_lowercase + "-_"
    base64_alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
    b64_to_plantuml = bytes.maketrans(base64_alphabet.encode("utf-8"), plantuml_alphabet.encode("utf-8"))
    return base64.b64encode(compressed_string).translate(b64_to_plantuml).decode("utf-8")


def _detect_error(response: httpx.Response, svg: str) -> Optional[str]:
    """Return an error message if the PlantUML server rendered an error image, else None."""
    header_err = response.headers.get("X-PlantUML-Diagram-Error")
    if header_err:
        line = response.headers.get("X-PlantUML-Diagram-Error-Line")
        return f"{header_err}" + (f" (line {line})" if line else "")
    for marker in _ERROR_MARKERS:
        if marker in svg:
            return "PlantUML syntax error in generated diagram"
    return None


async def render_plantuml_to_svg(plantuml_code: str) -> Tuple[str, Optional[str]]:
    """
    Render PlantUML DSL to SVG via the Docker PlantUML server.

    Returns (svg, error): `error` is None on a clean render, or a message when the
    server produced an error image (HTTP 200 but syntactically invalid input — this is
    how real syntax verification is done). Raises RuntimeError on transport failure.
    """
    encoded = encode_plantuml(plantuml_code)
    url = f"{settings.PLANTUML_SERVER_URL.rstrip('/')}/svg/{encoded}"
    try:
        response = await get_client().get(url)
    except Exception as e:
        logger.error("PlantUML server request failed: %s", e)
        raise RuntimeError(f"Failed to reach PlantUML server: {e}") from e

    if response.status_code != 200:
        raise RuntimeError(f"PlantUML server returned status {response.status_code}")

    svg = response.text
    error = _detect_error(response, svg)
    if error:
        logger.warning("PlantUML rendered an error image: %s", error)
    return svg, error


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
