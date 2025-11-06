"""
Test suite for diff-based file editing system.

Tests the search/replace functionality and fuzzy matching strategies.
"""

import sys
import os

# Add parent directory to path to import orchestrator modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator'))

from app.utils.code_patching import (
    extract_search_replace_blocks,
    apply_search_replace,
    apply_multiple_edits,
    is_search_replace_format,
    extract_edits_by_file
)


def test_extract_search_replace_blocks():
    """Test extraction of search/replace blocks from AI response."""
    print("\n=== Test 1: Extract Search/Replace Blocks ===")

    ai_response = """
I'll update the button color for you.

```
src/App.jsx
<<<<<<< SEARCH
  <button className="bg-blue-500 hover:bg-blue-700 text-white">
    Click Me
  </button>
=======
  <button className="bg-green-500 hover:bg-green-700 text-white">
    Click Me
  </button>
>>>>>>> REPLACE
```

Done!
"""

    edits = extract_search_replace_blocks(ai_response)

    assert len(edits) == 1, f"Expected 1 edit, got {len(edits)}"
    assert edits[0].file_path == "src/App.jsx", f"Wrong file path: {edits[0].file_path}"
    assert "bg-blue-500" in edits[0].search_content, "Search content missing expected text"
    assert "bg-green-500" in edits[0].replace_content, "Replace content missing expected text"

    print("[OK] Successfully extracted search/replace block")
    print(f"   File: {edits[0].file_path}")
    print(f"   Search: {edits[0].search_content[:50]}...")
    print(f"   Replace: {edits[0].replace_content[:50]}...")


def test_exact_match():
    """Test exact matching strategy."""
    print("\n=== Test 2: Exact Match ===")

    original = """
function greet(name) {
    return `Hello, ${name}!`;
}

function farewell(name) {
    return `Goodbye, ${name}!`;
}
"""

    search = """function greet(name) {
    return `Hello, ${name}!`;
}"""

    replace = """function greet(name) {
    return `Hi, ${name}! Welcome!`;
}"""

    result = apply_search_replace(original, search, replace, fuzzy=False)

    assert result.success, f"Edit failed: {result.error}"
    assert result.match_method == "exact", f"Wrong match method: {result.match_method}"
    assert "Hi, ${name}! Welcome!" in result.content, "Replacement not applied"
    assert "Goodbye" in result.content, "Other content was modified"

    print("[OK] Exact match successful")
    print(f"   Match method: {result.match_method}")
    print(f"   Result preview: {result.content[:100]}...")


def test_trimmed_match():
    """Test trimmed line endings matching strategy."""
    print("\n=== Test 3: Trimmed Line Endings Match ===")

    # Original has trailing spaces
    original = """
function calculate(a, b) {
    return a + b;
}
"""

    # Search doesn't have trailing spaces
    search = """function calculate(a, b) {
    return a + b;
}"""

    replace = """function calculate(a, b) {
    return a * b;
}"""

    result = apply_search_replace(original, search, replace, fuzzy=True)

    assert result.success, f"Edit failed: {result.error}"
    assert "a * b" in result.content, "Replacement not applied"

    print("[OK] Trimmed matching successful")
    print(f"   Match method: {result.match_method}")


def test_whitespace_normalized_match():
    """Test whitespace-normalized matching strategy."""
    print("\n=== Test 4: Whitespace Normalized Match ===")

    # Original has different indentation
    original = """
const  data  =  {
  name:    'John',
    age:     30
};
"""

    # Search has normalized whitespace
    search = """const data = {
  name: 'John',
  age: 30
};"""

    replace = """const data = {
  name: 'Jane',
  age: 25
};"""

    result = apply_search_replace(original, search, replace, fuzzy=True)

    assert result.success, f"Edit failed: {result.error}"
    assert "Jane" in result.content, "Replacement not applied"

    print("[OK] Whitespace normalized matching successful")
    print(f"   Match method: {result.match_method}")


def test_multiple_edits():
    """Test applying multiple edits sequentially."""
    print("\n=== Test 5: Multiple Edits ===")

    original = """
const API_URL = 'http://localhost:3000';
const APP_NAME = 'My App';
const VERSION = '1.0.0';
"""

    edits = [
        ("const API_URL = 'http://localhost:3000';", "const API_URL = 'https://api.example.com';"),
        ("const APP_NAME = 'My App';", "const APP_NAME = 'Tesslate Studio';"),
        ("const VERSION = '1.0.0';", "const VERSION = '2.0.0';")
    ]

    result = apply_multiple_edits(original, edits, fuzzy=True)

    assert result.success, f"Edits failed: {result.error}"
    assert "https://api.example.com" in result.content, "First edit not applied"
    assert "Tesslate Studio" in result.content, "Second edit not applied"
    assert "2.0.0" in result.content, "Third edit not applied"

    print("[OK] Multiple edits successful")
    print(f"   Applied 3 edits")
    print(f"   Result: {result.content.strip()}")


def test_format_detection():
    """Test automatic format detection."""
    print("\n=== Test 6: Format Detection ===")

    search_replace_response = """
src/App.jsx
<<<<<<< SEARCH
old code
=======
new code
>>>>>>> REPLACE
"""

    full_file_response = """
```javascript
// File: src/NewComponent.jsx
export default function NewComponent() {
  return <div>Hello</div>;
}
```
"""

    assert is_search_replace_format(search_replace_response), "Failed to detect search/replace format"
    assert not is_search_replace_format(full_file_response), "False positive for full file format"

    print("[OK] Format detection working correctly")


def test_edits_by_file():
    """Test grouping edits by file."""
    print("\n=== Test 7: Group Edits by File ===")

    response = """
src/App.jsx
<<<<<<< SEARCH
old code 1
=======
new code 1
>>>>>>> REPLACE

src/App.jsx
<<<<<<< SEARCH
old code 2
=======
new code 2
>>>>>>> REPLACE

src/utils.js
<<<<<<< SEARCH
old util
=======
new util
>>>>>>> REPLACE
"""

    by_file = extract_edits_by_file(response)

    assert len(by_file) == 2, f"Expected 2 files, got {len(by_file)}"
    assert "src/App.jsx" in by_file, "App.jsx not found"
    assert "src/utils.js" in by_file, "utils.js not found"
    assert len(by_file["src/App.jsx"]) == 2, f"Expected 2 edits for App.jsx, got {len(by_file['src/App.jsx'])}"
    assert len(by_file["src/utils.js"]) == 1, f"Expected 1 edit for utils.js, got {len(by_file['src/utils.js'])}"

    print("[OK] Edits grouped correctly by file")
    print(f"   Files: {list(by_file.keys())}")
    print(f"   App.jsx: {len(by_file['src/App.jsx'])} edits")
    print(f"   utils.js: {len(by_file['src/utils.js'])} edits")


def test_fuzzy_matching():
    """Test fuzzy matching with similar but not exact code."""
    print("\n=== Test 8: Fuzzy Matching ===")

    original = """
function processUser(userData) {
    const name = userData.name;
    const email = userData.email;
    return { name, email };
}
"""

    # Search has slightly different variable name
    search = """function processUser(data) {
    const name = data.name;
    const email = data.email;
    return { name, email };
}"""

    replace = """function processUser(userData) {
    const { name, email } = userData;
    return { name, email };
}"""

    result = apply_search_replace(original, search, replace, fuzzy=True)

    # Fuzzy matching should find a close match
    assert result.success, f"Fuzzy match failed: {result.error}"
    print("[OK] Fuzzy matching successful")
    print(f"   Match method: {result.match_method}")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("DIFF-BASED FILE EDITING TEST SUITE")
    print("=" * 60)

    tests = [
        test_extract_search_replace_blocks,
        test_exact_match,
        test_trimmed_match,
        test_whitespace_normalized_match,
        test_multiple_edits,
        test_format_detection,
        test_edits_by_file,
        test_fuzzy_matching,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] Test failed: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] Test error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
