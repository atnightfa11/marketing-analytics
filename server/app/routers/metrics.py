from fastapi import APIRouter
# Stub so Codex follows the schema shape: values plus variance and CIs
router = APIRouter()

@router.get("/api/metrics")
async def metrics():
    return {
        "uniques": {"value": 0, "variance": 0.0, "ci80": [0, 0], "ci95": [0, 0]},
        "sessions": {"value": 0, "variance": 0.0, "ci80": [0, 0], "ci95": [0, 0]},
        "pageviews": {"value": 0, "variance": 0.0, "ci80": [0, 0], "ci95": [0, 0]},
        "conversions": {"value": 0, "variance": 0.0, "ci80": [0, 0], "ci95": [0, 0]},
        "flags": {"low_confidence": False}
    }
