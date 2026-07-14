import urllib.request
import os

url = "https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar"
dest = os.path.join(os.path.dirname(__file__), "..", "plantuml.jar")

print(f"Downloading PlantUML from {url} to {dest}...")
try:
    urllib.request.urlretrieve(url, dest)
    print("Download complete!")
except Exception as e:
    print(f"Error downloading: {e}")
