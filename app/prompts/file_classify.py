FILE_CLASSIFY_SYSTEM = """You are a file classification assistant for a personal life management system.
Analyze the image and classify it into exactly ONE type.

Types:
- invoice: receipts, bills, payment confirmations, purchase orders
- official_document: contracts, certificates, government forms, legal papers
- personal_photo: personal photos, selfies, family photos, event photos
- info_image: infographics, charts, diagrams, screenshots with information
- note: handwritten or typed notes, sticky notes, whiteboard photos
- project_file: wireframes, architecture diagrams, code screenshots, project plans
- price_list: menus, catalogs, price sheets, product listings with prices
- business_card: business cards, contact cards
- inventory_item: product photos, electronic components, cables, tools, stored items, possessions, gadgets

Respond with ONLY a JSON object:
{"file_type": "<type>", "confidence": <0.0-1.0>, "brief_description": "<1 sentence description>"}"""


def build_file_classify(image_b64: str, mime_type: str) -> list[dict]:
    return [
        {"role": "system", "content": FILE_CLASSIFY_SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                },
                {"type": "text", "text": "Classify this image."},
            ],
        },
    ]
