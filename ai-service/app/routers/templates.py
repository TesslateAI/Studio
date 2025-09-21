from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from app.services.template_service import TemplateService
from app.schemas import TemplateRequest, TemplateResponse

router = APIRouter()
template_service = TemplateService()


@router.get("/", response_model=List[TemplateResponse])
async def list_templates():
    try:
        templates = await template_service.list_templates()
        return templates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str):
    try:
        template = await template_service.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        return template
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_from_template(request: TemplateRequest):
    try:
        result = await template_service.generate_from_template(
            template_id=request.template_id,
            variables=request.variables,
            customizations=request.customizations,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/list")
async def list_categories():
    try:
        categories = await template_service.list_categories()
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))