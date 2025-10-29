"""
Test the patch_file tool for agent mode diff editing.
"""

import sys
import os
import asyncio
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator'))

from app.agent.tools.file_tools import patch_file_tool
from app.config import get_settings


async def test_patch_file_tool():
    """Test the patch_file tool with a realistic scenario."""
    print("\n" + "="*70)
    print("TEST: patch_file Tool")
    print("="*70)

    # Setup test environment
    settings = get_settings()
    test_user_id = 999
    test_project_id = "test_patch"
    project_dir = f"users/{test_user_id}/{test_project_id}"

    # Create test directory and file
    os.makedirs(project_dir + "/src", exist_ok=True)

    original_content = """function App() {
  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white p-8 rounded-lg shadow-md">
        <h1 className="text-3xl font-bold text-gray-800 mb-4">Welcome!</h1>
        <p className="text-gray-600">Start building.</p>
      </div>
    </div>
  )
}

export default App
"""

    test_file = os.path.join(project_dir, "src/App.jsx")
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(original_content)

    print(f"\n✓ Created test file: {test_file}")
    print(f"  Original content: {len(original_content)} bytes")

    # Test 1: Simple color change
    print("\n=== Test 1: Change background color ===")

    params = {
        "file_path": "src/App.jsx",
        "search": '    <div className="min-h-screen bg-gray-100 flex items-center justify-center">',
        "replace": '    <div className="min-h-screen bg-blue-50 flex items-center justify-center">'
    }

    context = {
        "user_id": test_user_id,
        "project_id": test_project_id,
        "db": None  # Not needed for local filesystem
    }

    result = await patch_file_tool(params, context)

    if result["success"]:
        print(f"✅ Patch successful!")
        print(f"   Match method: {result['match_method']}")
        print(f"   Bytes written: {result['bytes_written']}")

        # Verify the change
        with open(test_file, 'r', encoding='utf-8') as f:
            new_content = f.read()

        assert "bg-blue-50" in new_content, "New color not found!"
        assert "bg-gray-100" not in new_content, "Old color still present!"
        assert "Welcome!" in new_content, "Other content was modified!"
        print("   ✓ Change verified correctly")
    else:
        print(f"❌ Patch failed: {result['message']}")
        return False

    # Test 2: Multiple line change
    print("\n=== Test 2: Change heading text ===")

    params = {
        "file_path": "src/App.jsx",
        "search": '        <h1 className="text-3xl font-bold text-gray-800 mb-4">Welcome!</h1>',
        "replace": '        <h1 className="text-3xl font-bold text-blue-600 mb-4">Welcome to Tesslate!</h1>'
    }

    result = await patch_file_tool(params, context)

    if result["success"]:
        print(f"✅ Patch successful!")
        print(f"   Match method: {result['match_method']}")

        # Verify
        with open(test_file, 'r', encoding='utf-8') as f:
            new_content = f.read()

        assert "Welcome to Tesslate!" in new_content
        assert "text-blue-600" in new_content
        assert "Welcome!" not in new_content or "Welcome to Tesslate!" in new_content
        print("   ✓ Change verified correctly")
    else:
        print(f"❌ Patch failed: {result['message']}")
        return False

    # Test 3: Fuzzy matching (slightly different whitespace)
    print("\n=== Test 3: Fuzzy matching with whitespace variation ===")

    params = {
        "file_path": "src/App.jsx",
        "search": '<p className="text-gray-600">Start building.</p>',  # No indentation
        "replace": '<p className="text-gray-600">Build amazing things!</p>'
    }

    result = await patch_file_tool(params, context)

    if result["success"]:
        print(f"✅ Patch successful with fuzzy matching!")
        print(f"   Match method: {result['match_method']}")

        # Verify
        with open(test_file, 'r', encoding='utf-8') as f:
            new_content = f.read()

        assert "Build amazing things!" in new_content
        print("   ✓ Fuzzy match worked correctly")
    else:
        print(f"❌ Patch failed: {result['message']}")
        return False

    # Test 4: File not found
    print("\n=== Test 4: File not found error ===")

    params = {
        "file_path": "src/NonExistent.jsx",
        "search": "foo",
        "replace": "bar"
    }

    result = await patch_file_tool(params, context)

    if not result["success"]:
        print(f"✅ Correctly returned error: {result['message']}")
    else:
        print(f"❌ Should have failed for non-existent file!")
        return False

    # Test 5: Search block not found
    print("\n=== Test 5: Search block not found ===")

    params = {
        "file_path": "src/App.jsx",
        "search": "this code does not exist in the file",
        "replace": "replacement"
    }

    result = await patch_file_tool(params, context)

    if not result["success"]:
        print(f"✅ Correctly returned error: {result['message']}")
        if "hint" in result:
            print(f"   Hint: {result['hint']}")
    else:
        print(f"❌ Should have failed for non-existent search block!")
        return False

    # Cleanup
    print("\n=== Cleanup ===")
    import shutil
    shutil.rmtree(f"users/{test_user_id}", ignore_errors=True)
    print("✓ Test files cleaned up")

    print("\n" + "="*70)
    print("ALL TESTS PASSED!")
    print("="*70)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_patch_file_tool())
    sys.exit(0 if success else 1)
