import requests

def test_ua():
    url = "https://www.analvids.com/filter/1?niche=double_anal&general=release"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Content Length: {len(response.text)}")
    print(f"Sample Content: {response.text[:500]}")

if __name__ == "__main__":
    test_ua()
