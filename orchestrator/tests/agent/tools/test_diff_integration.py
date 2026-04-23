"""
Integration test for diff-based editing with simulated AI responses.

Tests the complete flow from AI response → extraction → file editing → saving.
"""

import io
import os
import sys

import pytest

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

from app.utils.code_patching import (
    apply_multiple_edits,
    extract_edits_by_file,
    is_search_replace_format,
)

pytestmark = pytest.mark.unit


def test_simulated_ai_edit_flow():
    """
    Simulate the complete flow of an AI making edits to a React component.

    This tests what happens when:
    1. User has an existing App.jsx file
    2. User asks AI to change a button color
    3. AI responds with search/replace blocks
    4. System applies the edits
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Simulated AI Edit Flow")
    print("=" * 70)

    # Step 1: Original file content (what's in the project)
    print("\n📄 Step 1: Original file content")
    original_content = """import { useState } from 'react'
import './App.css'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white p-8 rounded-lg shadow-md">
        <h1 className="text-3xl font-bold mb-4">Welcome to Tesslate</h1>
        <p className="text-gray-600 mb-6">Count: {count}</p>
        <button
          onClick={() => setCount(count + 1)}
          className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"
        >
          Click me
        </button>
      </div>
    </div>
  )
}

export default App
"""

    print(f"   File length: {len(original_content)} characters")
    print("   Contains: bg-blue-500 ✓")

    # Step 2: User request
    print("\n💬 Step 2: User requests")
    user_request = "Change the button color from blue to green"
    print(f"   User: '{user_request}'")

    # Step 3: AI response with search/replace blocks
    print("\n🤖 Step 3: AI generates search/replace response")
    ai_response = """I'll change the button color from blue to green for you.

```
src/App.jsx
<<<<<<< SEARCH
        <button
          onClick={() => setCount(count + 1)}
          className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"
        >
          Click me
        </button>
=======
        <button
          onClick={() => setCount(count + 1)}
          className="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded"
        >
          Click me
        </button>
>>>>>>> REPLACE
```

The button now has a green background!
"""

    print(f"   Response length: {len(ai_response)} characters")
    print(f"   (vs {len(original_content)} if full file was regenerated)")
    token_savings = 100 - (len(ai_response) / len(original_content) * 100)
    print(f"   Token savings: ~{token_savings:.1f}%")

    # Step 4: Format detection
    print("\n🔍 Step 4: Format detection")
    is_diff_format = is_search_replace_format(ai_response)
    print(f"   Is search/replace format? {is_diff_format} ✓")

    # Step 5: Extract edits
    print("\n📋 Step 5: Extract edits from AI response")
    edits_by_file = extract_edits_by_file(ai_response)

    print(f"   Files to edit: {len(edits_by_file)}")
    for file_path, edits in edits_by_file.items():
        print(f"   - {file_path}: {len(edits)} edit(s)")
        for i, edit in enumerate(edits, 1):
            print(f"     Edit {i}:")
            print(f"       Search: '{edit.search_content[:50]}...'")
            print(f"       Replace: '{edit.replace_content[:50]}...'")

    # Step 6: Apply edits
    print("\n✏️ Step 6: Apply edits to file")
    file_path = "src/App.jsx"
    edits = edits_by_file[file_path]

    # Convert to tuples for apply_multiple_edits
    edit_tuples = [(edit.search_content, edit.replace_content) for edit in edits]

    result = apply_multiple_edits(original_content, edit_tuples, fuzzy=True)

    if not result.success:
        print(f"   ❌ Failed: {result.error}")
        return False

    print(f"   ✅ Success! Match method: {result.match_method}")

    # Step 7: Verify the edit
    print("\n🔎 Step 7: Verify changes")

    # Check that old code is gone
    assert "bg-blue-500" not in result.content, "Old blue color still present!"
    print("   ✓ Old code (bg-blue-500) removed")

    # Check that new code is present
    assert "bg-green-500" in result.content, "New green color not found!"
    print("   ✓ New code (bg-green-500) added")

    # Check that other code is preserved
    assert "useState" in result.content, "Other code was modified!"
    assert "min-h-screen" in result.content, "Container styling was modified!"
    assert "Welcome to Tesslate" in result.content, "Text content was modified!"
    print("   ✓ Surrounding code preserved")

    # Step 8: Show the diff
    print("\n📊 Step 8: Changes summary")
    print(f"   Original lines: {len(original_content.splitlines())}")
    print(f"   Modified lines: {len(result.content.splitlines())}")
    print(
        f"   Line count change: {len(result.content.splitlines()) - len(original_content.splitlines())}"
    )

    # Show the actual change
    print("\n   Actual change made:")
    print('   OLD: className="bg-blue-500 hover:bg-blue-700"')
    print('   NEW: className="bg-green-500 hover:bg-green-700"')

    print("\n✅ Integration test passed!")
    return True


def test_multiple_files_edit():
    """
    Test editing multiple files in one AI response.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Multiple Files Edit")
    print("=" * 70)

    # Original files
    app_content = """export default function App() {
  return <div className="app">
    <Header title="My App" />
    <Main />
  </div>
}"""

    header_content = """export default function Header({ title }) {
  return <header className="bg-blue-500">
    <h1>{title}</h1>
  </header>
}"""

    # AI response editing both files
    ai_response = """I'll update the header color and default title.

```
src/App.jsx
<<<<<<< SEARCH
    <Header title="My App" />
=======
    <Header title="OpenSail" />
>>>>>>> REPLACE
```

```
src/components/Header.jsx
<<<<<<< SEARCH
  return <header className="bg-blue-500">
=======
  return <header className="bg-green-500">
>>>>>>> REPLACE
```
"""

    print("\n📋 Extracting edits")
    edits_by_file = extract_edits_by_file(ai_response)

    print(f"   Files to edit: {len(edits_by_file)}")
    for file_path in edits_by_file:
        print(f"   - {file_path}")

    # Apply edits to each file
    print("\n✏️ Applying edits")

    # Edit App.jsx
    if "src/App.jsx" in edits_by_file:
        edits = [(e.search_content, e.replace_content) for e in edits_by_file["src/App.jsx"]]
        result = apply_multiple_edits(app_content, edits, fuzzy=True)
        assert result.success, f"Failed to edit App.jsx: {result.error}"
        assert 'title="OpenSail"' in result.content
        print("   ✅ src/App.jsx updated")

    # Edit Header.jsx
    if "src/components/Header.jsx" in edits_by_file:
        edits = [
            (e.search_content, e.replace_content)
            for e in edits_by_file["src/components/Header.jsx"]
        ]
        result = apply_multiple_edits(header_content, edits, fuzzy=True)
        assert result.success, f"Failed to edit Header.jsx: {result.error}"
        assert "bg-green-500" in result.content
        print("   ✅ src/components/Header.jsx updated")

    print("\n✅ Multiple files edit test passed!")
    return True


def test_fuzzy_matching_realistic():
    """
    Test fuzzy matching with realistic scenarios where AI's search block
    doesn't exactly match due to whitespace or minor differences.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Fuzzy Matching (Realistic Scenarios)")
    print("=" * 70)

    # Scenario 1: AI search has different indentation
    print("\n📝 Scenario 1: Different indentation")

    original = """  const data = {
    name: 'John',
    age: 30
  };"""

    # AI used 2 spaces, original uses 4 spaces
    search = """const data = {
  name: 'John',
  age: 30
};"""

    replace = """const data = {
  name: 'Jane',
  age: 25
};"""

    result = apply_multiple_edits(original, [(search, replace)], fuzzy=True)

    if result.success:
        print(f"   ✅ Matched using: {result.match_method}")
        assert "Jane" in result.content
    else:
        print(f"   ❌ Failed: {result.error}")
        return False

    # Scenario 2: AI search has extra/missing blank lines
    print("\n📝 Scenario 2: Extra blank lines")

    original = """function test() {
  console.log('hello');
  return true;
}"""

    search = """function test() {

  console.log('hello');

  return true;
}"""

    replace = """function test() {
  console.log('updated');
  return true;
}"""

    result = apply_multiple_edits(original, [(search, replace)], fuzzy=True)

    if result.success:
        print(f"   ✅ Matched using: {result.match_method}")
        assert "updated" in result.content
    else:
        print(f"   ❌ Failed: {result.error}")
        return False

    print("\n✅ Fuzzy matching test passed!")
    return True


def run_integration_tests():
    """Run all integration tests."""
    print("=" * 70)
    print("DIFF EDITING - INTEGRATION TEST SUITE")
    print("=" * 70)

    tests = [
        ("Simulated AI Edit Flow", test_simulated_ai_edit_flow),
        ("Multiple Files Edit", test_multiple_files_edit),
        ("Fuzzy Matching Realistic", test_fuzzy_matching_realistic),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"\n❌ {name} FAILED")
        except AssertionError as e:
            print(f"\n❌ {name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ {name} ERROR: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_integration_tests()
    sys.exit(0 if success else 1)
