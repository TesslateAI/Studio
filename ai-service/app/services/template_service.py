from typing import List, Dict, Any, Optional
import json
import os
from pathlib import Path

from app.schemas import TemplateResponse


class TemplateService:
    def __init__(self):
        self.templates_dir = Path(__file__).parent.parent / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        self._load_default_templates()

    async def list_templates(self) -> List[TemplateResponse]:
        templates = []
        for template_file in self.templates_dir.glob("*.json"):
            with open(template_file, "r") as f:
                template_data = json.load(f)
                templates.append(TemplateResponse(**template_data))
        return templates

    async def get_template(self, template_id: str) -> Optional[TemplateResponse]:
        template_file = self.templates_dir / f"{template_id}.json"
        if not template_file.exists():
            return None

        with open(template_file, "r") as f:
            template_data = json.load(f)
            return TemplateResponse(**template_data)

    async def generate_from_template(
        self,
        template_id: str,
        variables: Dict[str, Any],
        customizations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        generated_code = self._process_template(template, variables, customizations)

        return {
            "template_id": template_id,
            "generated_code": generated_code,
            "files": self._generate_file_structure(template, variables),
        }

    async def list_categories(self) -> List[str]:
        categories = set()
        for template_file in self.templates_dir.glob("*.json"):
            with open(template_file, "r") as f:
                template_data = json.load(f)
                categories.add(template_data.get("category", "Other"))
        return sorted(list(categories))

    def _load_default_templates(self):
        default_templates = [
            {
                "id": "react-component",
                "name": "React Component",
                "description": "Create a new React component with TypeScript",
                "category": "Frontend",
                "variables": [
                    {"name": "componentName", "type": "string", "required": True},
                    {"name": "props", "type": "array", "required": False},
                    {"name": "useState", "type": "boolean", "default": False},
                ],
                "preview": "export const Component: React.FC<Props> = () => { ... }",
            },
            {
                "id": "fastapi-endpoint",
                "name": "FastAPI Endpoint",
                "description": "Create a new FastAPI endpoint with validation",
                "category": "Backend",
                "variables": [
                    {"name": "routeName", "type": "string", "required": True},
                    {"name": "method", "type": "string", "required": True},
                    {"name": "requestModel", "type": "string", "required": False},
                    {"name": "responseModel", "type": "string", "required": False},
                ],
                "preview": "@router.post('/path') async def endpoint(): ...",
            },
            {
                "id": "docker-compose",
                "name": "Docker Compose Setup",
                "description": "Generate Docker Compose configuration",
                "category": "DevOps",
                "variables": [
                    {"name": "services", "type": "array", "required": True},
                    {"name": "networks", "type": "array", "required": False},
                    {"name": "volumes", "type": "array", "required": False},
                ],
                "preview": "version: '3.8'\nservices:\n  ...",
            },
        ]

        for template in default_templates:
            template_file = self.templates_dir / f"{template['id']}.json"
            if not template_file.exists():
                with open(template_file, "w") as f:
                    json.dump(template, f, indent=2)

    def _process_template(
        self,
        template: TemplateResponse,
        variables: Dict[str, Any],
        customizations: Optional[Dict[str, Any]] = None,
    ) -> str:
        return f"# Generated from template: {template.name}\n# TODO: Implement template processing"

    def _generate_file_structure(
        self, template: TemplateResponse, variables: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        return [
            {
                "path": f"generated/{template.id}/index.ts",
                "content": "// Generated file",
            }
        ]