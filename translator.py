import requests

url = "https://translate.googleapis.com/translate_a/single"
params = {
    "client": "gtx",
    "sl": "en",
    "tl": "ko",
    "dt": "t",
    "q": "flies"
}

response = requests.get(url, params=params, timeout=10)
print(response.json())