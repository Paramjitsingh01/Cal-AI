import json
import os
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

limiter = Limiter(key_func=get_remote_address, default_limits=["20/hour"])
app = FastAPI(title="Cal AI Nutrition API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Server is missing the GEMINI_API_KEY environment variable.",
        )
    return genai.Client(api_key=api_key)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Cal AI API is running", "health": "/health"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze")
@limiter.limit("10/minute")
async def analyze_food(request: Request, image: UploadFile = File(...)) -> Any:
    """Analyze one food image. The Gemini API key remains on the server."""
    mime_type = (image.content_type or "").lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Please upload a JPEG, PNG, or WebP image.",
        )

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large. Maximum size is 8 MB.")

    prompt = """
You are a careful nutrition estimation assistant. Inspect the food in this image.
Estimate a plausible serving size and nutrition values for the visible food.
Do not claim exact measurement from a photo. If the food or portion is unclear,
state that the estimate has low confidence. Return JSON only, matching this schema.
Use non-negative numeric values. calories_kcal is kcal; all macro values are grams.
If multiple foods are visible, estimate the whole plate total.
"""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "food_name": {"type": "STRING"},
            "serving_estimate": {"type": "STRING"},
            "calories_kcal": {"type": "NUMBER"},
            "protein_g": {"type": "NUMBER"},
            "carbs_g": {"type": "NUMBER"},
            "fat_g": {"type": "NUMBER"},
            "confidence": {"type": "STRING", "enum": ["low", "medium", "high"]},
            "notes": {"type": "STRING"},
        },
        "required": [
            "food_name", "serving_estimate", "calories_kcal",
            "protein_g", "carbs_g", "fat_g", "confidence", "notes"
        ],
    }

    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.2,
            ),
        )
        if not response.text:
            raise ValueError("Gemini returned an empty response.")
        result = json.loads(response.text)

        # Validate/normalize numeric fields before returning them to the app.
        numeric_fields = ["calories_kcal", "protein_g", "carbs_g", "fat_g"]
        for field in numeric_fields:
            value = float(result[field])
            if value < 0:
                raise ValueError(f"Invalid negative value for {field}")
            result[field] = round(value, 1)

        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception:
        # Avoid returning internal exception details or API-key-related information.
        raise HTTPException(
            status_code=502,
            detail="Food analysis failed. Please try again or check the backend logs.",
        )
