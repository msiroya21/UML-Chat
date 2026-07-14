import zlib
import httpx
import string

# PlantUML encoding map
PLANTUML_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"

def encode_plantuml(uml_text: str) -> str:
    """Encode PlantUML text for the HTTP API using raw deflate + custom base64."""
    # Raw deflate compression (wbits=-15)
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
    compressed = compressor.compress(uml_text.encode('utf-8')) + compressor.flush()
    
    # Custom base64-like encoding
    encoded = ""
    for i in range(0, len(compressed), 3):
        chunk = compressed[i:i+3]
        while len(chunk) < 3:
            chunk += b'\x00'
        
        b1, b2, b3 = chunk[0], chunk[1], chunk[2]
        
        c1 = b1 >> 2
        c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
        c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
        c4 = b3 & 0x3F
        
        encoded += PLANTUML_ALPHABET[c1] + PLANTUML_ALPHABET[c2] + PLANTUML_ALPHABET[c3] + PLANTUML_ALPHABET[c4]
        
    # Truncate padding if needed
    remainder = len(compressed) % 3
    if remainder == 1:
        encoded = encoded[:-2]
    elif remainder == 2:
        encoded = encoded[:-1]
        
    return encoded

async def test_api():
    uml_text = """@startuml
Bob -> Alice : Hello from API
@enduml"""
    encoded = encode_plantuml(uml_text)
    url = f"https://www.plantuml.com/plantuml/svg/{encoded}"
    print(f"Requesting SVG from: {url}")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200 and "<svg" in response.text:
            print("Successfully rendered SVG via public PlantUML API!")
            print(response.text[:200] + "...")
        else:
            print(f"Failed to render: Status {response.status_code}")

import asyncio
asyncio.run(test_api())
