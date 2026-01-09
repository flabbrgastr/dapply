import subprocess
from scraper import ScraperModule
from pathlib import Path

def test_w3m():
    url = "https://www.analvids.com/filter/1?niche=double_anal&general=release"
    scraper = ScraperModule(crawl_name="test_w3m")
    
    # Try w3m scraper manually
    try:
        cmd = ['w3m', '-dump', '-cols', '200', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        print(f"W3M Output Length: {len(result.stdout)}")
        print("W3M Sample Output:")
        print(result.stdout[:500])
    except Exception as e:
        print(f"W3M Error: {e}")

if __name__ == "__main__":
    test_w3m()
