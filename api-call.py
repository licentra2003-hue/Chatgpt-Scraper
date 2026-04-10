import requests

# The endpoint URL
url = "http://localhost:8000/scrape"

# The data payload (Python dictionary)
payload = {
    "query": "what are the best MMPs in India?",
    "save_files": False
}

# The headers
headers = {
    "Content-Type": "application/json"
}

try:
    # Making the POST request
    # Using the 'json' parameter automatically handles JSON encoding 
    # and sets the Content-Type header to application/json.
    response = requests.post(url, json=payload, headers=headers)

    # Raise an exception if the request was unsuccessful (4xx or 5xx)
    response.raise_for_status()

    # Parse and print the response
    data = response.json()
    print("Success!")
    print(data)

except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")