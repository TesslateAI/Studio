from typing import List
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import User, Chat, Message, Project, ProjectFile
from ..schemas import Chat as ChatSchema, Message as MessageSchema, MessageCreate
from ..auth import get_current_active_user
from ..config import get_settings
from openai import AsyncOpenAI
import json
import os
import aiofiles
import re
import asyncio

settings = get_settings()
router = APIRouter()

@router.get("/", response_model=List[ChatSchema])
async def get_chats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Chat).where(Chat.user_id == current_user.id)
    )
    chats = result.scalars().all()
    return chats

@router.post("/", response_model=ChatSchema)
async def create_chat(
    chat_data: dict,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    project_id = chat_data.get('project_id')
    
    # Check if chat already exists for this user and project
    if project_id:
        result = await db.execute(
            select(Chat).where(
                Chat.user_id == current_user.id,
                Chat.project_id == project_id
            )
        )
        existing_chat = result.scalar_one_or_none()
        if existing_chat:
            return existing_chat
    
    db_chat = Chat(
        user_id=current_user.id,
        project_id=project_id
    )
    db.add(db_chat)
    await db.commit()
    await db.refresh(db_chat)
    return db_chat

@router.get("/{project_id}/messages", response_model=List[MessageSchema])
async def get_project_messages(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all messages for a specific project's chat."""
    # Get the chat for this user and project
    result = await db.execute(
        select(Chat).where(
            Chat.user_id == current_user.id,
            Chat.project_id == project_id
        )
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        # No chat exists yet for this project, return empty list
        return []
    
    # Get all messages for this chat
    messages_result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at.asc())
    )
    messages = messages_result.scalars().all()
    return messages

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

manager = ConnectionManager()

@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    user = None
    try:
        # Verify token and get user
        from ..auth import jwt, settings, JWTError
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username = payload.get("sub")
        
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=1008)
            return
        
        await manager.connect(websocket, user.id)
        
        while True:
            try:
                data = await websocket.receive_json()
                await handle_chat_message(data, user, db, websocket)
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Error handling message: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Error: {str(e)}"
                    })
                except:
                    break
                    
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if user:
            manager.disconnect(user.id)

async def handle_chat_message(data: dict, user: User, db: AsyncSession, websocket: WebSocket):
    message_content = data.get("message")
    project_id = data.get("project_id")
    
    # Get or create chat for this user and project
    if project_id:
        result = await db.execute(
            select(Chat).where(
                Chat.user_id == user.id,
                Chat.project_id == project_id
            )
        )
        chat = result.scalar_one_or_none()
        
        if not chat:
            # Create new chat for this project
            chat = Chat(user_id=user.id, project_id=project_id)
            db.add(chat)
            await db.commit()
            await db.refresh(chat)
        
        chat_id = chat.id
    else:
        # Fallback to chat_id from frontend (for backwards compatibility)
        chat_id = data.get("chat_id", 1)
    
    # Save user message
    user_message = Message(
        chat_id=chat_id,
        role="user",
        content=message_content
    )
    db.add(user_message)
    await db.commit()
    
    # Get project context if available
    context = ""
    has_existing_files = False
    if project_id:
        result = await db.execute(
            select(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        files = result.scalars().all()
        if files:
            has_existing_files = True
            context = "\n\nProject files:\n"
            for file in files:
                context += f"\nFile: {file.file_path}\n{file.content}\n"
    
    # WebSocket is already connected if we got here
    
    # Stream response from OpenAI
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base
    )
    
    full_response = ""
    processed_files = set()
    
    # Build system prompt based on context
    base_system_prompt = """You are an expert React developer. Generate clean, modern React code for Vite applications using Tailwind CSS.

CRITICAL RULES:
1. DO EXACTLY WHAT IS ASKED.
2. USE STANDARD TAILWIND CLASSES ONLY. No `bg-background` or `text-foreground`. Use `bg-white`, `text-black`, `bg-blue-500`, etc.
3. FILE COUNT LIMITS: A simple change should only modify 1-2 files.
4. NO ROUTING LIBRARIES like `react-router-dom` unless explicitly asked. Use `<a>` tags.
5. PRESERVATION IS KEY (for edits): Do not rewrite entire components. Integrate your changes surgically. Preserve all existing logic, props, and state.
6. COMPLETENESS: Each file must be COMPLETE from the first line to the last. NO "..." or truncation.
7. NO CONVERSATION: Your output must contain ONLY code wrapped in the specified format.
8. When providing code, ALWAYS specify the filename at the top of the code block like:
```javascript
// File: path/to/file.js
<code>
9. ALWAYS PLAN AND MAKE A MULTIPAGE WEB APPLICATION. DO NOT CREATE SINGLE PAGE APPS. THEY SHOULD ALL BE CONNECTED.
```"""

    surgical_edit_prompt = """

CRITICAL: THIS IS AN EDIT TO AN EXISTING APPLICATION.

You MUST follow these rules:
1. DO NOT regenerate the entire application.
2. ONLY edit the EXACT files needed for the requested change.
3. If the user says "update the header", ONLY edit the Header component.
4. When adding a new component:
   - Create the new component file.
   - UPDATE ONLY the parent component that will use it.
5. NEVER TRUNCATE FILES. Always return COMPLETE files with ALL content. No "..." ellipsis.
6. You are a SURGEON making a precise incision, not an artist repainting the canvas. 99% of the original code should remain untouched."""

    system_prompt = base_system_prompt
    if has_existing_files:
        system_prompt += surgical_edit_prompt

    try:
        print(f"Calling AI API with model: {settings.openai_model}")
        print(f"API Base: {settings.openai_api_base}")
        
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{context}\n\nUser request: {message_content}"}
            ],
            stream=True,
            temperature=0.7
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                
                # Send stream chunk
                try:
                    await websocket.send_json({
                        "type": "stream",
                        "content": content
                    })
                except Exception as e:
                    print(f"WebSocket error during streaming: {e}")
                    return
        
        # Process all files at the end when response is complete
        if project_id:
            code_blocks = extract_complete_code_blocks(full_response)
            print(f"Processing {len(code_blocks)} files from completed response")
            
            for i, (file_path, code) in enumerate(code_blocks):
                if file_path not in processed_files:
                    print(f"📁 Saving file {i+1}/{len(code_blocks)}: {file_path}")
                    processed_files.add(file_path)
                    await save_file(file_path, code, project_id, user.id, db, websocket)
                    
                    # Small delay between files to prevent overwhelming dev server
                    if i < len(code_blocks) - 1:  # Don't delay after the last file
                        await asyncio.sleep(0.2)
                
    except Exception as e:
        print(f"Error during AI stream: {e}")
        await websocket.send_json({
            "type": "error",
            "content": f"Error: {str(e)}"
        })
        return
    
    # Save assistant message
    assistant_message = Message(
        chat_id=chat_id,
        role="assistant",
        content=full_response
    )
    db.add(assistant_message)
    await db.commit()
    
    # Send completion message
    try:
        await websocket.send_json({
            "type": "complete",
            "content": full_response
        })
        print("✅ Sent completion message to WebSocket")
    except Exception as e:
        print(f"❌ Error sending completion message: {e}")

def extract_complete_code_blocks(content: str):
    """Extract only complete code blocks with file paths"""
    # Improved pattern to catch proper file paths and avoid malformed ones
    patterns = [
        # Standard: ```language\n// File: path\ncode```
        r'```(?:\w+)?\s*\n(?://|#)\s*File:\s*([^\n]+\.[\w]+)\n(.*?)```',
        # Alternative: ```language\n# File: path\ncode``` 
        r'```(?:\w+)?\s*\n#\s*File:\s*([^\n]+\.[\w]+)\n(.*?)```',
        # Comment style: ```\n<!-- File: path -->\ncode```
        r'```[^\n]*\n<!--\s*File:\s*([^\n]+\.[\w]+)\s*-->\n(.*?)```',
        # Simple: ```javascript\npath\ncode``` (must have valid extension)
        r'```(?:\w+)?\s*\n([a-zA-Z0-9_/-]+\.[a-zA-Z0-9]+)\n(.*?)```'
    ]
    
    matches = []
    processed_paths = set()
    
    for pattern in patterns:
        found_matches = re.findall(pattern, content, re.DOTALL)
        for match in found_matches:
            file_path = match[0].strip()
            code = match[1].strip()
            
            # Clean up file path - remove any leading comment markers or "File:" text
            file_path = re.sub(r'^(?://|#|<!--)\s*(?:File:\s*)?', '', file_path)
            file_path = re.sub(r'\s*(?:-->)?\s*$', '', file_path)
            file_path = file_path.strip()
            
            # Validate file path
            if (file_path and 
                '.' in file_path and 
                not file_path.startswith('//') and 
                not file_path.startswith('#') and
                not file_path.startswith('File:') and
                file_path not in processed_paths and
                len(file_path) < 200 and  # Reasonable path length limit
                re.match(r'^[a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+$', file_path)):  # Valid characters only
                
                matches.append((file_path, code))
                processed_paths.add(file_path)
                print(f"Extracted file: {file_path}")
    
    return matches

async def save_file(file_path: str, code: str, project_id: int, user_id: int, db: AsyncSession, websocket: WebSocket):
    """Save file to database and filesystem, then notify frontend"""
    print(f"💾 Saving file: {file_path}")
    try:
        # Save to database
        result = await db.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id,
                ProjectFile.file_path == file_path
            )
        )
        db_file = result.scalar_one_or_none()
        
        if db_file:
            db_file.content = code
        else:
            db_file = ProjectFile(
                project_id=project_id,
                file_path=file_path,
                content=code
            )
            db.add(db_file)
        
        await db.commit()
        
        # Save to filesystem
        project_dir = f"users/{user_id}/projects/{project_id}"
        full_path = os.path.join(project_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        async with aiofiles.open(full_path, 'w', encoding='utf-8') as f:
            await f.write(code)
            await f.flush()  # Ensure data is written to disk
        
        # Notify frontend with the file
        try:
            await websocket.send_json({
                "type": "file_ready",
                "file_path": file_path,
                "content": code
            })
            print(f"✅ File ready: {file_path}")
        except Exception as e:
            print(f"WebSocket error notifying file ready: {e}")
            
    except Exception as e:
        print(f"❌ Error saving file {file_path}: {e}")