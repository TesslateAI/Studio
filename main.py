import os
import subprocess
import re
import argparse
import sys
import json
from pathlib import Path
from openai import OpenAI

# --- 1. PROMPT ENGINEERING (Exact Prompts from the Web App) ---

SYSTEM_PROMPT_ANALYZE_EDIT_INTENT = """
You are an expert at planning code searches. Your job is to create a search strategy to find the exact code that needs to be edited.

DO NOT GUESS which files to edit. Instead, provide specific search terms that will locate the code.

SEARCH STRATEGY RULES:
1. For text changes (e.g., "change 'Start Deploying' to 'Go Now'"):
   - Search for the EXACT text: "Start Deploying"
2. For style changes (e.g., "make header black"):
   - Search for component names: "Header", "<header"
   - Search for class names: "header", "navbar"
   - Search for className attributes containing relevant words
3. For removing elements (e.g., "remove the deploy button"):
   - Search for the button text or aria-label
   - Search for relevant IDs or data-testids
4. Be SPECIFIC:
   - Use exact capitalization for user-visible text
   - Include multiple search terms for redundancy

Respond with a JSON object containing 'reasoning' (your thought process) and 'searchTerms' (an array of strings).
"""

SYSTEM_PROMPT_GENERATION_BASE = """
You are an expert React developer. Generate clean, modern React code for Vite applications using Tailwind CSS.

CRITICAL RULES:
1. DO EXACTLY WHAT IS ASKED.
2. USE STANDARD TAILWIND CLASSES ONLY. No `bg-background` or `text-foreground`. Use `bg-white`, `text-black`, `bg-blue-500`, etc.
3. FILE COUNT LIMITS: A simple change should only modify 1-2 files.
4. NO ROUTING LIBRARIES like `react-router-dom` unless explicitly asked. Use `<a>` tags.
5. PRESERVATION IS KEY (for edits): Do not rewrite entire components. Integrate your changes surgically. Preserve all existing logic, props, and state.
6. COMPLETENESS: Each file must be COMPLETE from the first line to the last. NO "..." or truncation.
7. NO CONVERSATION: Your output must contain ONLY code wrapped in the specified XML format.
8. ALWAYS use the following XML format for every file:

<file path="src/components/Example.jsx">
// Your complete React component code here
</file>
"""

SYSTEM_PROMPT_SURGICAL_EDIT = """
CRITICAL: THIS IS AN EDIT TO AN EXISTING APPLICATION.

You MUST follow these rules:
1. DO NOT regenerate the entire application.
2. ONLY edit the EXACT files needed for the requested change.
3. If the user says "update the header", ONLY edit the Header component.
4. When adding a new component:
   - Create the new component file.
   - UPDATE ONLY the parent component that will use it.
5. NEVER TRUNCATE FILES. Always return COMPLETE files with ALL content. No "..." ellipsis.
6. You are a SURGEON making a precise incision, not an artist repainting the canvas. 99% of the original code should remain untouched.
"""

# --- 2. UTILITY AND HELPER FUNCTIONS ---

def print_colored(text, color):
    """Prints colored text to the console."""
    colors = {
        "header": "\033[95m", "blue": "\033[94m", "cyan": "\033[96m",
        "green": "\033[92m", "warning": "\033[93m", "fail": "\033[91m",
        "endc": "\033[0m", "bold": "\033[1m", "underline": "\033[4m",
    }
    print(f"{colors.get(color, '')}{text}{colors['endc']}")

def parse_ai_response_files(response_text):
    """Parses AI's response to extract file paths and content."""
    files = {}
    pattern = re.compile(r'<file path="([^"]+)">\n?(.*?)\n?</file>', re.DOTALL)
    matches = pattern.finditer(response_text)
    for match in matches:
        path = match.group(1).replace("\\", "/") # Normalize path separators
        content = match.group(2).strip()
        files[path] = content
    return files

def write_files_to_disk(project_path, files):
    """Writes a dictionary of files to the specified project path."""
    for file_path, content in files.items():
        full_path = Path(project_path) / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        print_colored(f"   Written -> {full_path}", "green")

def get_project_structure(project_path):
    """Returns a string summary of the project's file structure."""
    structure = []
    for root, _, files in os.walk(project_path):
        if "node_modules" in root:
            continue
        level = len(Path(root).relative_to(project_path).parts)
        indent = ' ' * 2 * level
        structure.append(f"{indent}{os.path.basename(root)}/")
        sub_indent = ' ' * 2 * (level + 1)
        for f in files:
            structure.append(f"{sub_indent}{f}")
    return "\n".join(structure)

# --- 3. CORE LOGIC CLASSES ---

class ViteProject:
    """Manages the local Vite project setup and dev server."""
    def __init__(self, project_name="ai_generated_app"):
        self.path = Path.cwd() / project_name
        self.server_process = None
        # ** FIX: Detect OS to correctly run shell commands **
        self.is_windows = sys.platform == "win32"

    def setup(self):
        """Creates the project directory and initializes a Vite project."""
        print_colored(f"Setting up Vite project at: {self.path}", "header")
        self.path.mkdir(exist_ok=True)
        
        files_to_write = {
            "package.json": """
{
  "name": "ai-app", "version": "1.0.0", "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": { "react": "^18.2.0", "react-dom": "^18.2.0" },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.0.0", "vite": "^4.3.9", "tailwindcss": "^3.3.0",
    "postcss": "^8.4.31", "autoprefixer": "^10.4.16"
  }
}""",
            "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\nexport default defineConfig({ plugins: [react()] });",
            "tailwind.config.js": "/** @type {import('tailwindcss').Config} */\nexport default {\n  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],\n  theme: { extend: {} },\n  plugins: [],\n};",
            "postcss.config.cjs": "module.exports = {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};",
            "index.html": '<!DOCTYPE html>\n<html lang="en">\n  <head><meta charset="UTF-8" /><title>AI App</title></head>\n  <body>\n    <div id="root"></div>\n    <script type="module" src="/src/main.jsx"></script>\n  </body>\n</html>',
            "src/main.jsx": "import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport App from './App.jsx';\nimport './index.css';\nReactDOM.createRoot(document.getElementById('root')).render(<App />);",
            "src/App.jsx": 'function App() { return <div className="min-h-screen flex items-center justify-center"><h1>App Ready</h1></div>; }\nexport default App;',
            "src/index.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;",
        }
        
        for path, content in files_to_write.items():
            (self.path / path).parent.mkdir(exist_ok=True, parents=True)
            (self.path / path).write_text(content.strip())
        
        print_colored("Running 'npm install'... (This may take a moment)", "cyan")
        # ** FIX: Use shell=True on Windows for npm commands **
        subprocess.run(
            "npm install", 
            cwd=self.path, 
            check=True, 
            capture_output=True, 
            shell=self.is_windows
        )
        print_colored("Project setup complete!", "green")

    def start_server(self):
        """Starts the Vite dev server."""
        if self.server_process:
            self.stop_server()
        print_colored("Starting Vite dev server at http://localhost:5173", "header")
        # ** FIX: Use shell=True on Windows for npm commands **
        self.server_process = subprocess.Popen(
            "npm run dev", 
            cwd=self.path,
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            shell=self.is_windows
        )
        
    def stop_server(self):
        """Stops the Vite dev server."""
        if self.server_process:
            print_colored("Stopping Vite dev server...", "warning")
            # Terminating a shell process on Windows requires a different approach
            if self.is_windows:
                subprocess.run(f"taskkill /F /PID {self.server_process.pid} /T", shell=True, capture_output=True)
            else:
                self.server_process.terminate()
            self.server_process.wait()
            self.server_process = None

class AIClient:
    """Manages interactions with the OpenAI-compatible API."""
    def __init__(self, api_key, base_url, model):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def get_completion(self, system_prompt, user_prompt):
        """Gets a single, non-streamed completion."""
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1
        )
        return completion.choices[0].message.content

    def stream_completion(self, system_prompt, user_prompt):
        """Streams a completion, yielding tokens."""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
            temperature=0.5
        )
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

# --- 4. MAIN WORKFLOW LOGIC ---
def handle_initial_generation(ai_client, project, initial_prompt):
    print_colored("\n--- Initial Generation Phase ---", "header")
    project.setup()
    system_prompt = SYSTEM_PROMPT_GENERATION_BASE
    user_prompt = f"Generate a new React application based on this idea: '{initial_prompt}'"
    print_colored("Generating initial code...", "cyan")
    full_response = ""
    for token in ai_client.stream_completion(system_prompt, user_prompt):
        sys.stdout.write(token)
        sys.stdout.flush()
        full_response += token
    print()
    files = parse_ai_response_files(full_response)
    if not files:
        raise ValueError("The AI did not return any files in the expected format.")
    print_colored("\nWriting generated files to disk...", "cyan")
    write_files_to_disk(project.path, files)
    project.start_server()

def handle_surgical_edit(ai_client, project, edit_prompt):
    print_colored(f"\n--- Surgical Edit: '{edit_prompt}' ---", "header")
    print_colored("1. Analyzing edit intent...", "cyan")
    structure = get_project_structure(project.path)
    analyze_user_prompt = f"Current project structure for context:\n{structure}\n\nUser request: \"{edit_prompt}\"\n\nCreate a search plan."
    search_plan_str = ai_client.get_completion(SYSTEM_PROMPT_ANALYZE_EDIT_INTENT, analyze_user_prompt)
    try:
        # The AI might return markdown with a JSON block
        json_match = re.search(r'```json\n(.*?)\n```', search_plan_str, re.DOTALL)
        if json_match:
            search_plan_str = json_match.group(1)
        search_plan = json.loads(search_plan_str)
        print_colored(f"   AI Search Plan: {search_plan.get('reasoning', 'No reasoning provided.')}", "green")
    except (json.JSONDecodeError, KeyError):
        print_colored("   Warning: Could not parse AI search plan. Using prompt as search terms.", "warning")
        search_plan = {"searchTerms": edit_prompt.split()}

    print_colored("2. Searching local files based on plan...", "cyan")
    search_terms = search_plan.get("searchTerms", [])
    search_results = []
    for p in project.path.glob('**/*'):
        if p.is_file() and "node_modules" not in str(p) and p.suffix in ['.jsx', '.js', '.html', '.css']:
            try:
                content = p.read_text(encoding='utf-8')
                if any(term.lower() in content.lower() for term in search_terms):
                    search_results.append(p)
                    print_colored(f"   Found relevant file: {p.relative_to(project.path)}", "green")
            except Exception:
                continue
    
    if not search_results:
        print_colored("   No specific files found. Using entire project as context.", "warning")
        target_files_paths = [p for p in project.path.glob('src/**/*') if p.is_file()]
    else:
        target_files_paths = search_results

    target_files_content = {
        str(p.relative_to(project.path)).replace("\\", "/"): p.read_text(encoding='utf-8') for p in target_files_paths
    }

    print_colored("3. Generating surgical edit...", "cyan")
    context_files_str = "\n\n".join(
        f'<file path="{path}">\n{content}\n</file>' for path, content in target_files_content.items()
    )
    edit_system_prompt = SYSTEM_PROMPT_GENERATION_BASE + "\n" + SYSTEM_PROMPT_SURGICAL_EDIT
    edit_user_prompt = f"CONTEXT - EXISTING FILES:\n{context_files_str}\n\nUSER REQUEST:\n\"{edit_prompt}\"\n\nGenerate the complete, updated content for ONLY the files that need changing."
    full_response = ""
    for token in ai_client.stream_completion(edit_system_prompt, edit_user_prompt):
        sys.stdout.write(token)
        sys.stdout.flush()
        full_response += token
    print()

    edited_files = parse_ai_response_files(full_response)
    if not edited_files:
        print_colored("Warning: AI returned no files to edit. No changes applied.", "warning")
        return

    print_colored("\n4. Applying edits...", "cyan")
    write_files_to_disk(project.path, edited_files)
    project.start_server() # Restart server
    print_colored("Edit applied and server restarted.", "green")

# --- 5. SCRIPT ENTRY POINT ---

def main():
    parser = argparse.ArgumentParser(description="AI-driven Vite React App Generator and Editor.")
    parser.add_argument("--api_key", required=True, help="Your OpenAI-compatible API key.")
    parser.add_argument("--base_url", help="[OPTIONAL] OpenAI-compatible API base URL for local models.")
    parser.add_argument("--model", required=True, help="The model name to use (e.g., gpt-4-turbo).")
    parser.add_argument("--prompt", required=True, help="The initial high-level prompt for website generation.")
    parser.add_argument("--project_name", default="ai_generated_app", help="The name of the folder for the project.")
    
    args = parser.parse_args()
    
    # If no base_url is provided, default to OpenAI's API
    base_url = args.base_url if args.base_url else "https://api.cerebras.ai/v1"

    client = AIClient(args.api_key, base_url, args.model)
    project = ViteProject(args.project_name)

    try:
        handle_initial_generation(client, project, args.prompt)
        while True:
            print_colored("\n--- Interactive Edit Mode ---", "header")
            print_colored("Your app is running at http://localhost:5173", "blue")
            edit_prompt = input("What would you like to change? (or type 'exit' to quit)\n> ")
            if edit_prompt.lower() == 'exit':
                break
            if not edit_prompt.strip():
                continue
            handle_surgical_edit(client, project, edit_prompt)
    except Exception as e:
        print_colored(f"\nAn error occurred: {e}", "fail")
        import traceback
        traceback.print_exc()
    finally:
        project.stop_server()
        print_colored("\nScript finished.", "header")

if __name__ == "__main__":
    main()