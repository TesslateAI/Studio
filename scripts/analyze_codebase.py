#!/usr/bin/env python3
"""
Comprehensive Codebase Analysis Tool
Analyzes Python and TypeScript/JavaScript files to find:
- Unused functions/classes
- Duplicate code
- Dead code
- Function call graphs
- Dependency maps
"""

import ast
import os
import re
import json
import hashlib
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from datetime import datetime


class PythonAnalyzer:
    """Analyzes Python files using AST"""

    def __init__(self):
        self.definitions = {}  # {file: {name: (type, line, node)}}
        self.calls = defaultdict(set)  # {name: set of files that call it}
        self.imports = defaultdict(set)  # {file: set of imports}
        self.duplicates = defaultdict(list)  # {hash: [files]}

    def analyze_file(self, file_path: str) -> Dict:
        """Analyze a single Python file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=file_path)
            file_info = {
                'functions': [],
                'classes': [],
                'imports': [],
                'calls': [],
                'complexity': 0
            }

            for node in ast.walk(tree):
                # Track function definitions
                if isinstance(node, ast.FunctionDef):
                    func_info = {
                        'name': node.name,
                        'line': node.lineno,
                        'args': [arg.arg for arg in node.args.args],
                        'is_async': isinstance(node, ast.AsyncFunctionDef),
                        'decorators': [self._get_decorator_name(d) for d in node.decorator_list]
                    }
                    file_info['functions'].append(func_info)

                    if file_path not in self.definitions:
                        self.definitions[file_path] = {}
                    self.definitions[file_path][node.name] = ('function', node.lineno, node)

                # Track class definitions
                elif isinstance(node, ast.ClassDef):
                    class_info = {
                        'name': node.name,
                        'line': node.lineno,
                        'bases': [self._get_name(base) for base in node.bases],
                        'methods': []
                    }

                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            class_info['methods'].append(item.name)

                    file_info['classes'].append(class_info)

                    if file_path not in self.definitions:
                        self.definitions[file_path] = {}
                    self.definitions[file_path][node.name] = ('class', node.lineno, node)

                # Track imports
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        file_info['imports'].append({
                            'type': 'import',
                            'name': alias.name,
                            'alias': alias.asname
                        })
                        self.imports[file_path].add(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        file_info['imports'].append({
                            'type': 'from',
                            'module': module,
                            'name': alias.name,
                            'alias': alias.asname
                        })
                        self.imports[file_path].add(f"{module}.{alias.name}")

                # Track function calls
                elif isinstance(node, ast.Call):
                    call_name = self._get_name(node.func)
                    if call_name:
                        file_info['calls'].append(call_name)
                        self.calls[call_name].add(file_path)

            # Calculate complexity
            file_info['complexity'] = self._calculate_complexity(tree)

            return file_info

        except Exception as e:
            return {'error': str(e)}

    def _get_decorator_name(self, node) -> str:
        """Extract decorator name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        return str(node)

    def _get_name(self, node) -> str:
        """Extract name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_name(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        return ''

    def _calculate_complexity(self, tree) -> int:
        """Calculate cyclomatic complexity"""
        complexity = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        return complexity


class TypeScriptAnalyzer:
    """Analyzes TypeScript/JavaScript files using regex patterns"""

    def __init__(self):
        self.definitions = {}
        self.calls = defaultdict(set)
        self.imports = defaultdict(set)

    def analyze_file(self, file_path: str) -> Dict:
        """Analyze a TypeScript/JavaScript file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            file_info = {
                'functions': [],
                'classes': [],
                'components': [],
                'imports': [],
                'exports': [],
                'hooks': []
            }

            # Find function declarations
            func_patterns = [
                r'function\s+(\w+)\s*\(',  # function name()
                r'const\s+(\w+)\s*=\s*(?:async\s+)?function',  # const name = function
                r'const\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>', # const name = () =>
                r'export\s+(?:async\s+)?function\s+(\w+)',  # export function name
            ]

            for pattern in func_patterns:
                for match in re.finditer(pattern, content):
                    func_name = match.group(1)
                    line_num = content[:match.start()].count('\n') + 1
                    file_info['functions'].append({
                        'name': func_name,
                        'line': line_num
                    })

            # Find class declarations
            class_pattern = r'class\s+(\w+)'
            for match in re.finditer(class_pattern, content):
                class_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                file_info['classes'].append({
                    'name': class_name,
                    'line': line_num
                })

            # Find React components (function components)
            component_pattern = r'(?:export\s+)?(?:const|function)\s+([A-Z]\w+)\s*[=:]?\s*(?:\([^)]*\))?\s*(?::\s*React\.FC|=>\s*{|{\s*return)'
            for match in re.finditer(component_pattern, content):
                comp_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                file_info['components'].append({
                    'name': comp_name,
                    'line': line_num
                })

            # Find imports
            import_patterns = [
                r'import\s+(?:{[^}]+}|[\w\s,]+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                r'import\s+[\'"]([^\'"]+)[\'"]',
            ]

            for pattern in import_patterns:
                for match in re.finditer(pattern, content):
                    import_path = match.group(1)
                    file_info['imports'].append(import_path)
                    self.imports[file_path].add(import_path)

            # Find exports
            export_patterns = [
                r'export\s+(?:default\s+)?(?:class|function|const)\s+(\w+)',
                r'export\s+{\s*([^}]+)\s*}',
            ]

            for pattern in export_patterns:
                for match in re.finditer(pattern, content):
                    file_info['exports'].append(match.group(1))

            # Find React hooks
            hook_pattern = r'(use[A-Z]\w+)'
            hooks = set(re.findall(hook_pattern, content))
            file_info['hooks'] = list(hooks)

            return file_info

        except Exception as e:
            return {'error': str(e)}


class CodebaseAnalyzer:
    """Main analyzer that coordinates Python and TypeScript analysis"""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.python_analyzer = PythonAnalyzer()
        self.ts_analyzer = TypeScriptAnalyzer()
        self.files_analyzed = []
        self.results = {
            'python': {},
            'typescript': {},
            'statistics': {},
            'unused': [],
            'duplicates': [],
            'recommendations': []
        }

        # Directories to ignore
        self.ignore_dirs = {
            'node_modules', '.venv', 'venv', '__pycache__',
            'dist', 'build', '.git', 'alembic/versions',
            'base-cache'
        }

    def should_analyze(self, file_path: Path) -> bool:
        """Check if file should be analyzed"""
        # Check if in ignored directory
        for part in file_path.parts:
            if part in self.ignore_dirs or part.startswith('.'):
                return False
        return True

    def find_files(self) -> Tuple[List[Path], List[Path]]:
        """Find all Python and TypeScript files"""
        python_files = []
        ts_files = []

        for ext in ['**/*.py']:
            for file_path in self.root_dir.glob(ext):
                if self.should_analyze(file_path):
                    python_files.append(file_path)

        for ext in ['**/*.ts', '**/*.tsx', '**/*.js', '**/*.jsx']:
            for file_path in self.root_dir.glob(ext):
                if self.should_analyze(file_path):
                    ts_files.append(file_path)

        return python_files, ts_files

    def analyze(self):
        """Run complete analysis"""
        print("Starting codebase analysis...")

        python_files, ts_files = self.find_files()

        print(f"Found {len(python_files)} Python files")
        print(f"Found {len(ts_files)} TypeScript/JavaScript files")

        # Analyze Python files
        print("\nAnalyzing Python files...")
        for file_path in python_files:
            rel_path = str(file_path.relative_to(self.root_dir))
            result = self.python_analyzer.analyze_file(str(file_path))
            self.results['python'][rel_path] = result
            self.files_analyzed.append(rel_path)

        # Analyze TypeScript files
        print("Analyzing TypeScript/JavaScript files...")
        for file_path in ts_files:
            rel_path = str(file_path.relative_to(self.root_dir))
            result = self.ts_analyzer.analyze_file(str(file_path))
            self.results['typescript'][rel_path] = result
            self.files_analyzed.append(rel_path)

        # Find unused code
        print("\nFinding unused code...")
        self._find_unused_code()

        # Find duplicates
        print("Finding duplicate code...")
        self._find_duplicates()

        # Calculate statistics
        print("Calculating statistics...")
        self._calculate_statistics()

        # Generate recommendations
        print("Generating recommendations...")
        self._generate_recommendations()

        print("\nAnalysis complete!")

    def _find_unused_code(self):
        """Find potentially unused functions and classes"""
        # Python unused code
        all_definitions = set()
        all_calls = set()

        for file_path, defs in self.python_analyzer.definitions.items():
            for name, (def_type, line, _) in defs.items():
                # Skip special methods and private functions
                if name.startswith('_') and not name.startswith('__'):
                    continue
                if name in ['main', '__init__', '__main__']:
                    continue

                all_definitions.add((file_path, name, def_type, line))

        # Collect all called names
        for file_path, info in self.results['python'].items():
            if 'calls' in info:
                all_calls.update(info['calls'])

        # Find definitions that are never called
        for file_path, name, def_type, line in all_definitions:
            if name not in all_calls:
                # Check if it's exported or used in the same file
                file_calls = self.results['python'].get(file_path, {}).get('calls', [])
                if name not in file_calls:
                    self.results['unused'].append({
                        'file': file_path,
                        'name': name,
                        'type': def_type,
                        'line': line,
                        'language': 'python'
                    })

        # TypeScript unused exports
        for file_path, info in self.results['typescript'].items():
            if 'error' in info:
                continue

            # Components and functions that aren't imported anywhere
            exports = set()
            exports.update([f['name'] for f in info.get('functions', [])])
            exports.update([c['name'] for c in info.get('components', [])])
            exports.update([c['name'] for c in info.get('classes', [])])

            # Check if exported items are imported anywhere
            all_imports = set()
            for other_file, other_info in self.results['typescript'].items():
                if other_file != file_path and 'imports' in other_info:
                    for imp in other_info['imports']:
                        # Extract imported names from the import path
                        if file_path.replace('\\', '/') in imp or Path(file_path).stem in imp:
                            all_imports.add(Path(file_path).stem)

            # Note: This is a simplified check, actual unused detection would need more sophisticated import tracking

    def _find_duplicates(self):
        """Find duplicate or very similar code"""
        # Group files by hash of their content
        file_hashes = defaultdict(list)

        # Python files
        for file_path in self.results['python'].keys():
            try:
                full_path = self.root_dir / file_path
                with open(full_path, 'rb') as f:
                    content = f.read()
                    file_hash = hashlib.md5(content).hexdigest()
                    file_hashes[file_hash].append(('python', file_path))
            except:
                pass

        # TypeScript files
        for file_path in self.results['typescript'].keys():
            try:
                full_path = self.root_dir / file_path
                with open(full_path, 'rb') as f:
                    content = f.read()
                    file_hash = hashlib.md5(content).hexdigest()
                    file_hashes[file_hash].append(('typescript', file_path))
            except:
                pass

        # Find exact duplicates
        for file_hash, files in file_hashes.items():
            if len(files) > 1:
                self.results['duplicates'].append({
                    'type': 'exact',
                    'files': [f[1] for f in files],
                    'count': len(files)
                })

        # Find similar function names (potential duplicates)
        func_names = defaultdict(list)

        for file_path, info in self.results['python'].items():
            if 'functions' in info:
                for func in info['functions']:
                    func_names[func['name']].append(('python', file_path, func['line']))

        for file_path, info in self.results['typescript'].items():
            if 'functions' in info:
                for func in info['functions']:
                    func_names[func['name']].append(('typescript', file_path, func['line']))

        # Report functions with same name in different files
        for func_name, locations in func_names.items():
            if len(locations) > 1:
                # Filter out common names like 'render', 'init', etc.
                common_names = {'render', 'init', 'setup', 'main', 'test', 'create', 'update', 'delete'}
                if func_name.lower() not in common_names:
                    self.results['duplicates'].append({
                        'type': 'similar_names',
                        'name': func_name,
                        'locations': [{'file': loc[1], 'line': loc[2]} for loc in locations],
                        'count': len(locations)
                    })

    def _calculate_statistics(self):
        """Calculate overall statistics"""
        stats = {
            'total_files': len(self.files_analyzed),
            'python_files': len(self.results['python']),
            'typescript_files': len(self.results['typescript']),
            'total_functions': 0,
            'total_classes': 0,
            'total_components': 0,
            'unused_count': len(self.results['unused']),
            'duplicate_groups': len(self.results['duplicates']),
            'high_complexity_files': [],
            'large_files': []
        }

        # Count functions and classes
        for info in self.results['python'].values():
            if 'functions' in info:
                stats['total_functions'] += len(info['functions'])
            if 'classes' in info:
                stats['total_classes'] += len(info['classes'])

        for info in self.results['typescript'].values():
            if 'functions' in info:
                stats['total_functions'] += len(info['functions'])
            if 'classes' in info:
                stats['total_classes'] += len(info['classes'])
            if 'components' in info:
                stats['total_components'] += len(info['components'])

        # Find high complexity files
        for file_path, info in self.results['python'].items():
            if info.get('complexity', 0) > 20:
                stats['high_complexity_files'].append({
                    'file': file_path,
                    'complexity': info['complexity']
                })

        self.results['statistics'] = stats

    def _generate_recommendations(self):
        """Generate actionable recommendations"""
        recommendations = []

        # Recommend removing unused code
        if len(self.results['unused']) > 0:
            recommendations.append({
                'priority': 'high',
                'category': 'unused_code',
                'message': f"Found {len(self.results['unused'])} potentially unused functions/classes",
                'action': 'Review and remove unused code to reduce codebase size',
                'items': self.results['unused'][:10]  # Show top 10
            })

        # Recommend deduplication
        exact_dupes = [d for d in self.results['duplicates'] if d['type'] == 'exact']
        if len(exact_dupes) > 0:
            recommendations.append({
                'priority': 'high',
                'category': 'duplicates',
                'message': f"Found {len(exact_dupes)} exact duplicate files",
                'action': 'Remove duplicate files to reduce codebase size',
                'items': exact_dupes
            })

        # Recommend refactoring complex files
        high_complexity = self.results['statistics'].get('high_complexity_files', [])
        if len(high_complexity) > 0:
            recommendations.append({
                'priority': 'medium',
                'category': 'complexity',
                'message': f"Found {len(high_complexity)} files with high complexity",
                'action': 'Consider refactoring complex files for better maintainability',
                'items': high_complexity[:5]
            })

        # Similar function names
        similar_funcs = [d for d in self.results['duplicates'] if d['type'] == 'similar_names']
        if len(similar_funcs) > 5:
            recommendations.append({
                'priority': 'medium',
                'category': 'naming',
                'message': f"Found {len(similar_funcs)} functions with duplicate names across files",
                'action': 'Review these functions - they might be duplicates or need better naming',
                'items': similar_funcs[:10]
            })

        self.results['recommendations'] = recommendations

    def save_results(self, output_dir: str):
        """Save analysis results to JSON files"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save complete results
        results_file = output_path / f"analysis_{timestamp}.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2)

        print(f"\nSaved complete analysis to: {results_file}")

        # Save human-readable summary
        summary_file = output_path / f"summary_{timestamp}.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            self._write_summary(f)

        print(f"Saved summary to: {summary_file}")

        # Save unused code list
        if self.results['unused']:
            unused_file = output_path / f"unused_code_{timestamp}.txt"
            with open(unused_file, 'w', encoding='utf-8') as f:
                f.write("POTENTIALLY UNUSED CODE\n")
                f.write("=" * 80 + "\n\n")
                for item in sorted(self.results['unused'], key=lambda x: x['file']):
                    f.write(f"{item['file']}:{item['line']} - {item['type']} '{item['name']}'\n")
            print(f"Saved unused code list to: {unused_file}")

        # Save duplicates list
        if self.results['duplicates']:
            dupes_file = output_path / f"duplicates_{timestamp}.txt"
            with open(dupes_file, 'w', encoding='utf-8') as f:
                f.write("DUPLICATE CODE\n")
                f.write("=" * 80 + "\n\n")

                for dup in self.results['duplicates']:
                    if dup['type'] == 'exact':
                        f.write(f"\nExact duplicates ({dup['count']} files):\n")
                        for file in dup['files']:
                            f.write(f"  - {file}\n")
                    elif dup['type'] == 'similar_names':
                        f.write(f"\nFunction '{dup['name']}' appears in {dup['count']} files:\n")
                        for loc in dup['locations']:
                            f.write(f"  - {loc['file']}:{loc['line']}\n")
                    f.write("\n")

            print(f"Saved duplicates list to: {dupes_file}")

        return results_file

    def _write_summary(self, f):
        """Write human-readable summary"""
        stats = self.results['statistics']

        f.write("=" * 80 + "\n")
        f.write("CODEBASE ANALYSIS SUMMARY\n")
        f.write("=" * 80 + "\n\n")

        f.write("STATISTICS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total files analyzed: {stats['total_files']}\n")
        f.write(f"  Python files: {stats['python_files']}\n")
        f.write(f"  TypeScript/JavaScript files: {stats['typescript_files']}\n\n")

        f.write(f"Total functions: {stats['total_functions']}\n")
        f.write(f"Total classes: {stats['total_classes']}\n")
        f.write(f"Total React components: {stats['total_components']}\n\n")

        f.write(f"Potentially unused items: {stats['unused_count']}\n")
        f.write(f"Duplicate code groups: {stats['duplicate_groups']}\n\n")

        f.write("\nRECOMMENDATIONS\n")
        f.write("-" * 80 + "\n")

        for i, rec in enumerate(self.results['recommendations'], 1):
            f.write(f"\n{i}. [{rec['priority'].upper()}] {rec['category']}\n")
            f.write(f"   {rec['message']}\n")
            f.write(f"   Action: {rec['action']}\n")

        f.write("\n\n")
        f.write("=" * 80 + "\n")
        f.write("See detailed JSON and TXT files for complete analysis\n")
        f.write("=" * 80 + "\n")


def main():
    """Main entry point"""
    import sys

    # Get root directory from command line or use current directory
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    output_dir = sys.argv[2] if len(sys.argv) > 2 else './analysis-output'

    analyzer = CodebaseAnalyzer(root_dir)
    analyzer.analyze()
    analyzer.save_results(output_dir)

    # Print summary to console
    print("\n" + "=" * 80)
    print("ANALYSIS SUMMARY")
    print("=" * 80)

    stats = analyzer.results['statistics']
    print(f"\nFiles: {stats['total_files']} ({stats['python_files']} Python, {stats['typescript_files']} TS/JS)")
    print(f"Functions: {stats['total_functions']}")
    print(f"Classes: {stats['total_classes']}")
    print(f"Components: {stats['total_components']}")
    print(f"\nUnused items: {stats['unused_count']}")
    print(f"Duplicate groups: {stats['duplicate_groups']}")

    if analyzer.results['recommendations']:
        print(f"\nTop recommendations:")
        for rec in analyzer.results['recommendations'][:3]:
            print(f"  - [{rec['priority']}] {rec['message']}")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
