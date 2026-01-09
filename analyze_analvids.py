from bs4 import BeautifulSoup
import os

def analyze_analvids():
    filepath = "data/scrapes/crawl_1767871132/anvids_dapnew/filter_1_niche_double_anal_general_release.html"
    if not os.path.exists(filepath):
        print("File not found")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')
    
    # Let's find all cards
    cards = soup.find_all('div', class_=lambda x: x and 'card-scene' in x)
    print(f"Total cards found: {len(cards)}")
    
    if cards:
        first_card = cards[0]
        print("\n--- First Card Analysis ---")
        
        # Title and URL
        title_tag = first_card.find('div', class_='card-scene__text')
        if title_tag and title_tag.find('a'):
            a_tag = title_tag.find('a')
            print(f"Title: {a_tag.get('title')}")
            print(f"URL: {a_tag.get('href')}")
        
        # Duration
        time_tag = first_card.find('div', class_='label--time')
        if time_tag:
            print(f"Time: {time_tag.get_text(strip=True)}")
            
        # Metadata labels (like 4k, bts)
        labels = first_card.find_all('div', class_='label')
        label_texts = [l.get_text(strip=True) for l in labels if 'label--time' not in l.get('class', [])]
        print(f"Labels: {label_texts}")

if __name__ == "__main__":
    analyze_analvids()
