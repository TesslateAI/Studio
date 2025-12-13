#!/usr/bin/env python3
"""Test file extraction functionality"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.routers.chat import extract_complete_code_blocks

# Test with example AI response
test_response = """Here is the code:

```javascript
// File: src/App.jsx
import React from 'react';

export default function App() {
  return <div>Hello World</div>;
}
```

And another file:

```css
// File: src/index.css
body {
  margin: 0;
  font-family: Arial, sans-serif;
}
```
"""

files = extract_complete_code_blocks(test_response)
print(f'Extracted {len(files)} files:')
for file_path, code in files:
    print(f'  - {file_path} ({len(code)} chars)')
    print(f'    First 50 chars: {repr(code[:50])}')