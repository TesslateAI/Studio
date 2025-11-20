#!/usr/bin/env python3
"""
Analyze file dependencies in the codebase
"""
import os
import re
from pathlib import Path
from collections import defaultdict
import json

def count_lines(filepath):
    """Count lines in a file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return len(f.readlines())
    except:
        return 0

def extract_python_imports(filepath):
    """Extract imports from Python files"""
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Match: from X import Y, from .X import Y
        from_imports = re.findall(r'from\s+(\.{0,3}[\w\.]+)\s+import', content)
        imports.extend(from_imports)

        # Match: import X, import X.Y
        direct_imports = re.findall(r'^\s*import\s+([\w\.]+)', content, re.MULTILINE)
        imports.extend(direct_imports)

    except:
        pass
    return imports

def extract_ts_imports(filepath):
    """Extract imports from TypeScript/TSX files"""
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Match: import X from 'Y', import { X } from 'Y'
        patterns = [
            r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]',
            r'import\s+[\'"]([^\'"]+)[\'"]',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content)
            imports.extend(matches)

    except:
        pass
    return imports

def normalize_path(base_path, current_file, import_path):
    """Normalize an import path to absolute path"""
    current_dir = os.path.dirname(current_file)

    # Handle relative imports
    if import_path.startswith('.'):
        resolved = os.path.normpath(os.path.join(current_dir, import_path))
        return resolved

    return import_path

def analyze_directory(base_dir, extensions, extract_fn):
    """Analyze a directory for dependencies"""
    files = {}
    dependencies = defaultdict(list)

    for root, _, filenames in os.walk(base_dir):
        for filename in filenames:
            if any(filename.endswith(ext) for ext in extensions):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, base_dir)

                # Get file info
                lines = count_lines(filepath)
                imports = extract_fn(filepath)

                files[rel_path] = {
                    'path': filepath,
                    'lines': lines,
                    'imports': imports,
                    'raw_imports': imports
                }

                # Track dependencies
                for imp in imports:
                    dependencies[rel_path].append(imp)

    return files, dependencies

def main():
    base_dir = r'c:\Users\smirxs\Documents\Programming\Tesslate-Studio'

    # Analyze Python files
    print("Analyzing Python files...")
    py_dir = os.path.join(base_dir, 'orchestrator', 'app')
    py_files, py_deps = analyze_directory(py_dir, ['.py'], extract_python_imports)

    # Analyze TypeScript files
    print("Analyzing TypeScript files...")
    ts_dir = os.path.join(base_dir, 'app', 'src')
    ts_files, ts_deps = analyze_directory(ts_dir, ['.ts', '.tsx'], extract_ts_imports)

    # Combine results
    results = {
        'python': {
            'files': py_files,
            'dependencies': dict(py_deps)
        },
        'typescript': {
            'files': ts_files,
            'dependencies': dict(ts_deps)
        }
    }

    # Find large files (>1000 lines)
    print("\nLarge files (>1000 lines):")
    large_files = []
    for lang, data in results.items():
        for filepath, info in data['files'].items():
            if info['lines'] > 1000:
                large_files.append((lang, filepath, info['lines']))
                print(f"  [{lang}] {filepath}: {info['lines']} lines")

    # Find orphaned files (no imports)
    print("\nChecking for orphaned files...")

    # Save to JSON
    output_file = os.path.join(base_dir, 'dependency_analysis.json')
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nAnalysis complete. Results saved to {output_file}")
    print(f"Python files analyzed: {len(py_files)}")
    print(f"TypeScript files analyzed: {len(ts_files)}")
    print(f"Large files found: {len(large_files)}")

if __name__ == '__main__':
    main()
