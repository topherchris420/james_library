import json

with open('ruff_errors.json') as f:
    for e in json.load(f):
        print(f"{e['filename']}:{e['location']['row']} - {e['message']}")
