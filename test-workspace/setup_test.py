#!/usr/bin/env python3
import shutil
import os

# Copy template to test workspace
template_dir = r"C:\Users\Smirk\Documents\Programming\8-22-25-Studio\builder\backend\template"
test_dir = r"C:\Users\Smirk\Documents\Programming\8-22-25-Studio\test-workspace"

# Remove existing files except this script
for item in os.listdir(test_dir):
    if item != 'setup_test.py':
        item_path = os.path.join(test_dir, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)

# Copy template files
for item in os.listdir(template_dir):
    src_path = os.path.join(template_dir, item)
    dst_path = os.path.join(test_dir, item)
    
    if os.path.isdir(src_path):
        if item != '__pycache__':
            shutil.copytree(src_path, dst_path)
    else:
        shutil.copy2(src_path, dst_path)

print("Test workspace setup complete!")