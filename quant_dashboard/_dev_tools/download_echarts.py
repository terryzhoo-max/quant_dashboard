import urllib.request
import os

url = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"
target = "echarts.min.js"

try:
    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, target)
    size = os.path.getsize(target)
    print(f"Success! Saved to {target} ({size} bytes)")
    if size < 1000:
        print("!!! Error: Downloaded file is too small. Likely a 404.")
except Exception as e:
    print(f"Error: {e}")
