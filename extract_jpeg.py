#!/usr/bin/env python3
"""Extract base64 JPEG data from rain_lab_trifold.html bundler manifest"""

import json
import re
import sys

def extract_base64_jpeg(html_file):
    """Parse HTML and extract the base64 JPEG data from the manifest"""
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the manifest script tag
    manifest_match = re.search(r'<script type="__bundler/manifest">\s*(\{.*?\})\s*</script>', content, re.DOTALL)
    
    if not manifest_match:
        print("Error: Could not find __bundler/manifest script tag", file=sys.stderr)
        return None
    
    manifest_json = manifest_match.group(1)
    
    try:
        manifest = json.loads(manifest_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing manifest JSON: {e}", file=sys.stderr)
        return None
    
    # Find the JPEG entry (should be the first/only one with image/jpeg mime type)
    for uuid, entry in manifest.items():
        if entry.get('mime') == 'image/jpeg':
            return entry.get('data')
    
    print("Error: No JPEG found in manifest", file=sys.stderr)
    return None

if __name__ == '__main__':
    base64_data = extract_base64_jpeg('assets/marketing/rain_lab_trifold.html')
    
    if base64_data:
        # Save to file
        with open('rain_lab_trifold.jpg.b64', 'w') as f:
            f.write(base64_data)
        print(f"✓ Extracted {len(base64_data)} characters of base64 data")
        print(f"✓ Saved to: rain_lab_trifold.jpg.b64")
        
        # Also save as data URI for easy viewing
        data_uri = f"data:image/jpeg;base64,{base64_data}"
        with open('rain_lab_trifold.data-uri.txt', 'w') as f:
            f.write(data_uri)
        print(f"✓ Saved data URI to: rain_lab_trifold.data-uri.txt")
    else:
        sys.exit(1)
