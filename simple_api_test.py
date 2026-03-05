import requests
import json

# Test the API with a simple request
response = requests.post(
    "http://localhost:3005/api/scrape",
    headers={"Content-Type": "application/json"},
    json={"query": "What is the distance to the moon?"}
)

print(f"Status Code: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")
