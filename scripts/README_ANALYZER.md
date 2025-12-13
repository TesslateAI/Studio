# Code Analysis Tool

A comprehensive codebase analyzer that helps identify unused code, duplicates, and opportunities for reducing project size.

## Features

- **AST-based analysis** for Python files
- **Regex-based analysis** for TypeScript/JavaScript files
- **Unused code detection** - finds functions and classes that aren't being called
- **Duplicate detection** - identifies exact file duplicates and similar function names
- **Complexity analysis** - flags files with high cyclomatic complexity
- **Detailed reports** - generates JSON and human-readable reports

## Usage

### Basic Usage

```bash
python scripts/analyze_codebase.py
```

This will analyze the current directory and save results to `./analysis-output`

### Custom Paths

```bash
python scripts/analyze_codebase.py <root_directory> <output_directory>
```

Example:
```bash
python scripts/analyze_codebase.py . my-analysis-results
```

## Output Files

The tool generates several files in the output directory:

1. **analysis_TIMESTAMP.json** - Complete analysis data in JSON format
2. **summary_TIMESTAMP.txt** - Human-readable summary with statistics
3. **unused_code_TIMESTAMP.txt** - List of potentially unused functions/classes
4. **duplicates_TIMESTAMP.txt** - List of duplicate files and similar function names

## Interpreting Results

### Unused Code
Files listed in the unused code report contain functions or classes that:
- Are not called anywhere in the codebase
- Are not special methods (like `__init__`, `__main__`)
- Are not private methods (starting with `_`)

**Note:** Some items may be false positives:
- Functions used dynamically (via getattr, imports, etc.)
- API endpoints and route handlers
- Functions imported by external code

### Duplicates
Two types of duplicates are identified:
1. **Exact duplicates** - Files with identical content (MD5 hash)
2. **Similar names** - Functions with the same name in different files (may or may not be duplicates)

### Complexity
Files with cyclomatic complexity > 20 are flagged as high complexity and may benefit from refactoring.

## Ignored Directories

The analyzer automatically ignores:
- `node_modules`
- `.venv`, `venv`
- `__pycache__`
- `dist`, `build`
- `.git`
- `alembic/versions`
- `base-cache`

## Recommendations Priority

- **HIGH** - Should be addressed soon (unused code, exact duplicates)
- **MEDIUM** - Consider addressing (complexity, naming issues)
- **LOW** - Nice to have improvements

## Example Workflow

1. Run the analysis:
   ```bash
   python scripts/analyze_codebase.py
   ```

2. Review the summary file for an overview

3. Check the unused code list and verify items are truly unused

4. Remove unused code or add comments explaining why it's kept

5. Check duplicates and consolidate where appropriate

6. Review high-complexity files for refactoring opportunities

7. Re-run analysis to track progress

## Integration

The `analysis-output/` folder is gitignored, so analysis results won't be committed to version control.

## Limitations

- TypeScript/JavaScript analysis uses regex patterns, not a full parser
- Import/export tracking is simplified
- Dynamic code patterns may not be detected
- External API consumers are not tracked
