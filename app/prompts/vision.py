VISION_PROMPTS: dict[str, str] = {
    "invoice": """Extract all information from this invoice/receipt.
Return a JSON object:
{
  "vendor": "store/company name",
  "date": "YYYY-MM-DD or null",
  "total_amount": <number or null>,
  "currency": "SAR or detected currency",
  "items": [{"name": "item", "quantity": 1, "price": 0.0}],
  "payment_method": "cash/card/null",
  "notes": "any additional info"
}""",
    "official_document": """Extract key information from this official document.
Return a JSON object:
{
  "document_type": "contract/certificate/form/etc",
  "title": "document title",
  "parties": ["party1", "party2"],
  "key_terms": ["term1", "term2"],
  "dates": {"issued": "YYYY-MM-DD", "expiry": "YYYY-MM-DD or null"},
  "summary": "brief summary of the document"
}""",
    "personal_photo": """Describe this personal photo in detail.
Return a JSON object:
{
  "description": "detailed description of the scene",
  "people_count": <number>,
  "location_hint": "indoor/outdoor/specific place if identifiable",
  "mood": "happy/casual/formal/etc",
  "tags": ["tag1", "tag2", "tag3"]
}""",
    "info_image": """Extract all text and information from this image.
Return a JSON object:
{
  "extracted_text": "all readable text",
  "content_type": "chart/infographic/screenshot/diagram/etc",
  "key_information": ["point1", "point2"],
  "summary": "brief summary of the content"
}""",
    "note": """Extract the content from this note.
Return a JSON object:
{
  "content": "full text of the note",
  "note_type": "handwritten/typed/whiteboard",
  "language": "ar/en/mixed",
  "key_points": ["point1", "point2"],
  "action_items": ["item1", "item2"]
}""",
    "project_file": """Analyze this project-related file/screenshot.
Return a JSON object:
{
  "file_description": "what this file shows",
  "project_context": "what project or work this relates to",
  "technologies": ["tech1", "tech2"],
  "key_details": ["detail1", "detail2"],
  "notes": "any relevant observations"
}""",
    "price_list": """Extract pricing information from this image.
Return a JSON object:
{
  "vendor": "store/company name",
  "items": [{"name": "item", "price": 0.0, "unit": "per piece/kg/etc"}],
  "currency": "SAR or detected currency",
  "validity": "valid until date or null",
  "notes": "any conditions or offers"
}""",
    "business_card": """Extract contact information from this business card.
Return a JSON object:
{
  "name": "person name",
  "title": "job title",
  "company": "company name",
  "phone": "phone number or null",
  "email": "email or null",
  "website": "website or null",
  "address": "address or null",
  "other": "any other info"
}""",
    "inventory_item": """Identify this item/product and extract all useful details.
Return a JSON object:
{
  "item_name": "descriptive name of the item",
  "brand": "brand/manufacturer or null",
  "model": "model number or null",
  "description": "detailed description including color, size, distinguishing features",
  "category": "electronics/cables/tools/parts/accessories/household/other",
  "condition": "new/used/damaged/unknown",
  "estimated_value": null,
  "quantity_visible": 1,
  "specifications": ["spec1", "spec2"],
  "barcode_visible": "any visible barcode/QR code text or null",
  "notes": "any other relevant info"
}""",
}

VISION_ANALYSIS_SYSTEM = """You are a visual analysis assistant for a personal life management system.
Analyze the image carefully and extract structured information.
Respond with ONLY a JSON object as specified in the extraction instructions."""


def build_vision_analysis(
    image_b64: str, file_type: str, mime_type: str, user_context: str = ""
) -> list[dict]:
    prompt_text = VISION_PROMPTS.get(file_type, VISION_PROMPTS["info_image"])
    user_parts: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
        },
        {"type": "text", "text": prompt_text},
    ]
    if user_context:
        user_parts.append(
            {"type": "text", "text": f"\nAdditional context from user: {user_context}"}
        )
    return [
        {"role": "system", "content": VISION_ANALYSIS_SYSTEM},
        {"role": "user", "content": user_parts},
    ]
