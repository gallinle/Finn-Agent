# extraction/contracts.py
import base64, anthropic
client = anthropic.Anthropic()

def extract(pdf_bytes: bytes) -> Vertrag:
    resp = client.messages.parse(
        model="claude-opus-5-5",
        max_tokens=16000,
        output_config={"effort": "high"},
        system=SYSTEM_PROMPT,   # "Du liest wie ein Finanzreferent. Du rechnest nicht. ..."
        messages=[{"role": "user", "content": [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(pdf_bytes).decode()},
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Extrahiere alle Financial Covenants inkl. Definitionen aus Anlagen."},
        ]}],
        output_format=Vertrag,
    )
    return resp.parsed_output