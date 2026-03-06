#!/usr/bin/env python3
"""
Build a Mermaid diagram from dependency analysis
"""
import json
import os
from collections import defaultdict

def load_analysis():
    """Load the dependency analysis JSON"""
    with open('dependency_analysis.json', 'r') as f:
        return json.load(f)

def normalize_module_name(import_str, current_file, base='orchestrator.app'):
    """Convert import string to module name"""
    if import_str.startswith('.'):
        # Relative import
        parts = current_file.replace('\\', '/').replace('.py', '').split('/')
        levels = len(import_str) - len(import_str.lstrip('.'))
        import_path = import_str.lstrip('.')

        # Go up directories based on dots
        base_parts = parts[:-levels] if levels > 0 else parts[:-1]
        if import_path:
            base_parts.extend(import_path.split('.'))

        return '/'.join(base_parts)
    return import_str

def get_short_name(filepath):
    """Get a short display name for a file"""
    return filepath.replace('\\', '/').split('/')[-1].replace('.py', '').replace('.tsx', '').replace('.ts', '')

def get_folder(filepath):
    """Get the folder name"""
    parts = filepath.replace('\\', '/').split('/')
    if len(parts) > 1:
        return parts[0]
    return 'root'

def sanitize_id(name):
    """Sanitize a name for use as a Mermaid node ID"""
    return name.replace('/', '_').replace('\\', '_').replace('.', '_').replace('-', '_')

def build_dependency_map(data):
    """Build a map of who imports whom"""
    imports_map = defaultdict(set)
    imported_by = defaultdict(set)
    all_files = set()

    for filepath, info in data['files'].items():
        all_files.add(filepath)
        for imp in info['imports']:
            # Try to resolve to actual file
            resolved = resolve_import(imp, filepath, data['files'])
            if resolved:
                imports_map[filepath].add(resolved)
                imported_by[resolved].add(filepath)

    return imports_map, imported_by, all_files

def resolve_import(import_str, current_file, all_files):
    """Try to resolve an import to an actual file"""
    # Handle relative imports
    if import_str.startswith('.'):
        current_dir = os.path.dirname(current_file)
        levels = len(import_str) - len(import_str.lstrip('.'))
        import_path = import_str.lstrip('.')

        # Go up directories
        parts = current_dir.replace('\\', '/').split('/')
        if levels > 0:
            parts = parts[:-levels]

        if import_path:
            parts.extend(import_path.split('.'))

        # Try to find matching file
        possible_path = '/'.join(parts)
        for f in all_files:
            f_normalized = f.replace('\\', '/').replace('.py', '')
            if possible_path in f_normalized or f_normalized.endswith(possible_path):
                return f

    return None

def build_mermaid_diagram(py_data, ts_data):
    """Build the Mermaid diagram"""
    lines = ['graph TB']
    lines.append('')

    # Build dependency maps
    py_imports, py_imported_by, py_all_files = build_dependency_map(py_data)
    ts_imports, ts_imported_by, ts_all_files = build_dependency_map(ts_data)

    # Find orphaned files
    py_orphaned = {f for f in py_all_files if f not in py_imported_by and not py_imports.get(f)}
    ts_orphaned = {f for f in ts_all_files if f not in ts_imported_by and not ts_imports.get(f)}

    # Large files threshold
    LARGE_FILE_THRESHOLD = 1000

    # Group Python files by folder
    py_by_folder = defaultdict(list)
    for filepath in sorted(py_all_files):
        folder = get_folder(filepath)
        py_by_folder[folder].append(filepath)

    # Group TypeScript files by folder
    ts_by_folder = defaultdict(list)
    for filepath in sorted(ts_all_files):
        folder = get_folder(filepath)
        ts_by_folder[folder].append(filepath)

    # Python subgraphs
    lines.append('  %% Python Backend Files')
    for folder in sorted(py_by_folder.keys()):
        files = py_by_folder[folder]
        if len(files) > 0:
            folder_id = sanitize_id(f'py_{folder}')
            lines.append(f'  subgraph {folder_id}["{folder}"]')

            for filepath in files:
                node_id = sanitize_id(f'py_{filepath}')
                short_name = get_short_name(filepath)
                info = py_data['files'][filepath]
                lines_count = info['lines']

                # Determine styling
                style_class = ''
                if filepath in py_orphaned:
                    style_class = ':::orphaned'
                elif lines_count > LARGE_FILE_THRESHOLD:
                    style_class = ':::largefile'

                lines.append(f'    {node_id}["{short_name}<br/>{lines_count}L"]{style_class}')

            lines.append('  end')
            lines.append('')

    # TypeScript subgraphs
    lines.append('  %% TypeScript Frontend Files')
    for folder in sorted(ts_by_folder.keys()):
        files = ts_by_folder[folder]
        if len(files) > 0:
            folder_id = sanitize_id(f'ts_{folder}')
            lines.append(f'  subgraph {folder_id}["{folder}"]')

            for filepath in files:
                node_id = sanitize_id(f'ts_{filepath}')
                short_name = get_short_name(filepath)
                info = ts_data['files'][filepath]
                lines_count = info['lines']

                # Determine styling
                style_class = ''
                if filepath in ts_orphaned:
                    style_class = ':::orphaned'
                elif lines_count > LARGE_FILE_THRESHOLD:
                    style_class = ':::largefile'

                lines.append(f'    {node_id}["{short_name}<br/>{lines_count}L"]{style_class}')

            lines.append('  end')
            lines.append('')

    # Add edges for Python dependencies
    lines.append('  %% Python Dependencies')
    for source, targets in py_imports.items():
        source_id = sanitize_id(f'py_{source}')
        for target in targets:
            target_id = sanitize_id(f'py_{target}')
            lines.append(f'  {source_id} --> {target_id}')

    lines.append('')

    # Add edges for TypeScript dependencies
    lines.append('  %% TypeScript Dependencies')
    for source, targets in ts_imports.items():
        source_id = sanitize_id(f'ts_{source}')
        for target in targets:
            target_id = sanitize_id(f'ts_{target}')
            lines.append(f'  {source_id} --> {target_id}')

    lines.append('')

    # Styling
    lines.append('  %% Styling')
    lines.append('  classDef orphaned fill:#ff6b6b,stroke:#c92a2a,color:#fff')
    lines.append('  classDef largefile fill:#ffd43b,stroke:#fab005,color:#000')

    return '\n'.join(lines)

def main():
    """Main function"""
    data = load_analysis()

    print("Building Mermaid diagram...")
    diagram = build_mermaid_diagram(data['python'], data['typescript'])

    # Save to file
    output_file = 'dependency_diagram.mmd'
    with open(output_file, 'w') as f:
        f.write(diagram)

    print(f"Mermaid diagram saved to {output_file}")
    print(f"\nDiagram size: {len(diagram)} characters")

    # Also create a simplified version focusing on key files
    print("\nCreating simplified diagram...")

    return diagram

if __name__ == '__main__':
    main()
