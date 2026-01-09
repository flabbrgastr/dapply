import csv
import os
import requests
import json
import re
import time
import yaml

def load_config(config_path):
    config = {}
    if not os.path.exists(config_path):
        return config
    with open(config_path, 'r') as f:
        for line in f:
            if '=' in line:
                parts = line.split('=')
                if len(parts) >= 2:
                    key = parts[0].strip()
                    value = '='.join(parts[1:]).strip().strip('"').strip("'")
                    config[key] = value
    return config

def load_prompts(prompts_path):
    with open(prompts_path, 'r') as f:
        data = yaml.safe_load(f)
    return data.get('prompts', [])

def clean_title(title):
    # Remove URLs
    title = re.sub(r'https?://\S+', '', title)
    # Remove hashtags and their content
    title = re.sub(r'#\w+', '', title)
    # Remove special symbols
    title = re.sub(r'[➨☺|]', '', title)
    # Remove multiple spaces
    title = re.sub(r'\s+', ' ', title)
    return title.strip()

def call_llm(config, model, prompt_template, title):
    cleaned = clean_title(title)
    if not cleaned:
        return "NO_NAME"
        
    prompt = prompt_template.format(title=cleaned)
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.get('OPENAI_API_KEY', 'test23@test34')}"
    }
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }
    
    # Exponential backoff requested: 3, 6, 12, 24, 48
    backoff_sequence = [3, 6, 12, 24, 48]
    
    api_base = config.get('OPENAI_API_BASE', "https://amd1.mooo.com:8123/v1")
    
    for attempt, delay in enumerate([0] + backoff_sequence):
        if delay > 0:
            print(f"      [Retry] Waiting {delay}s...")
            time.sleep(delay)
            
        try:
            response = requests.post(
                f"{api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
            elif response.status_code in [429, 500, 502, 503, 504]:
                print(f"      [Error {response.status_code}] Attempt {attempt+1}/{len(backoff_sequence)+1}")
            else:
                print(f"      [Error {response.status_code}] for model {model}")
                return f"ERROR_{response.status_code}"
        except Exception as e:
            print(f"      [Exception] {e}")
            
    return "ERROR_MAX_RETRIES"

def main():
    config_path = '/Users/johannwaldherr/code/fg/dap/docs/prompt.config'
    prompts_path = '/Users/johannwaldherr/code/fg/dap/docs/prompts.yaml'
    input_csv = '/Users/johannwaldherr/code/fg/dap/extracted.csv'
    output_jsonl = '/Users/johannwaldherr/code/fg/dap/multi_model_test_results.jsonl'
    
    config = load_config(config_path)
    prompts = load_prompts(prompts_path)
    
    # Models to test - now from config
    models_raw = config.get('MODELS', '')
    if models_raw:
        models = [m.strip() for m in models_raw.split(',') if m.strip()]
    else:
        # Fallback if config is missing the key
        models = [config.get('OPENAI_MODEL', 'ollama@gemma3:1b')]
    
    # Load already processed (model, prompt_id, title) to skip
    processed = set()
    if os.path.exists(output_jsonl):
        with open(output_jsonl, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    res = json.loads(line)
                    # Only skip if it actually succeeded
                    if not res['output'].startswith("ERROR"):
                        key = (res['model'], res['prompt_id'], res['title'])
                        processed.add(key)
                except:
                    continue

    print(f"Starting Multi-Model Test...")
    print(f"Models: {models}")
    print(f"Prompts: {[p['id'] for p in prompts]}")
    print()

    # Load ALL titles from extracted.csv
    # Split into validation set (has performers) and extraction set (NO_NAME)
    validation_titles = []  # (title, expected_performers)
    extraction_titles = []  # titles with NO_NAME
    
    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get('title', '').strip()
            perf = row.get('performers', '').strip()
            
            if not title:
                continue
                
            if perf and perf.upper() != "NO_NAME":
                # Use first 50 titles with known performers for validation
                if len(validation_titles) < 50:
                    validation_titles.append((title, perf))
            else:
                # All NO_NAME titles for extraction
                extraction_titles.append(title)
    
    print(f"Loaded {len(validation_titles)} validation titles (with known performers)")
    print(f"Loaded {len(extraction_titles)} extraction titles (NO_NAME)")
    print()
    
    results_count = 0
    
    # Process validation set first
    print("=" * 80)
    print("PHASE 1: VALIDATION (Testing against known performers)")
    print("=" * 80)
    for title, expected in validation_titles:
        print(f"\nTitle: {title[:70]}...")
        print(f"Expected: {expected}")
        
        for model in models:
            for p in prompts:
                prompt_id = p['id']
                key = (model, prompt_id, title)
                
                if key in processed:
                    continue
                
                output = call_llm(config, model, p['template'], title)
                
                result_entry = {
                    "title": title,
                    "model": model,
                    "prompt_id": prompt_id,
                    "output": output,
                    "expected": expected,
                    "phase": "validation",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "rating": ""
                }
                
                # Append result immediately
                with open(output_jsonl, 'a', encoding='utf-8') as fout:
                    fout.write(json.dumps(result_entry) + "\n")
                
                if not output.startswith("ERROR"):
                    processed.add(key)
                    results_count += 1
                    print(f"  [{model}|{prompt_id}] -> {output}")

    # Process extraction set
    print("\n" + "=" * 80)
    print("PHASE 2: EXTRACTION (Processing NO_NAME titles)")
    print("=" * 80)
    for title in extraction_titles:
        print(f"\nTitle: {title[:70]}...")
        
        for model in models:
            for p in prompts:
                prompt_id = p['id']
                key = (model, prompt_id, title)
                
                if key in processed:
                    continue
                
                output = call_llm(config, model, p['template'], title)
                
                result_entry = {
                    "title": title,
                    "model": model,
                    "prompt_id": prompt_id,
                    "output": output,
                    "phase": "extraction",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "rating": ""
                }
                
                # Append result immediately
                with open(output_jsonl, 'a', encoding='utf-8') as fout:
                    fout.write(json.dumps(result_entry) + "\n")
                
                if not output.startswith("ERROR"):
                    processed.add(key)
                    results_count += 1
                    print(f"  [{model}|{prompt_id}] -> {output}")

    print(f"\n{'=' * 80}")
    print(f"Test session complete. Total new successful entries: {results_count}")
    print(f"Results stored in {output_jsonl}")
    print(f"{'=' * 80}")

if __name__ == "__main__":
    main()
