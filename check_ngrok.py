#!/usr/bin/env python
import urllib.request
import json

try:
    r = urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=3)
    data = json.loads(r.read().decode())
    print("\n=== NGROK ACTIVE TUNNELS ===\n")
    for tunnel in data.get('tunnels', []):
        print(f"Protocol: {tunnel['proto'].upper()}")
        print(f"Public URL: {tunnel['public_url']}")
        print(f"Local Address: {tunnel['config']['addr']}")
        print()
except Exception as e:
    print(f"Error: {e}")
    print("\nngrok API not responding on 127.0.0.1:4040")
