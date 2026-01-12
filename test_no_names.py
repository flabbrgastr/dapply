import csv
import os
import requests
import json
import re
import time
import yaml
import argparse
import pandas as pd
from datetime import datetime

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

def normalize_names(name_str, separator=','):
    if not name_str or name_str.upper() == "NO_NAME":
        return set()
    
    # Handle both comma and semicolon
    names = re.split(r'[;,]', name_str)
    return {n.strip().lower() for n in names if n.strip()}

def calculate_metrics(expected_str, actual_str):
    expected_set = normalize_names(expected_str, separator=';') # CSV uses ;
    actual_set = normalize_names(actual_str, separator=',')     # LLM uses ,
    
    # If both are empty (NO_NAME), that's a match
    if not expected_set and not actual_set:
        return 1.0, 1.0, 1.0, True
        
    # If one is empty but not the other
    if not expected_set or not actual_set:
        return 0.0, 0.0, 0.0, False
        
    tp = len(expected_set.intersection(actual_set))
    fp = len(actual_set - expected_set)
    fn = len(expected_set - actual_set)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    exact_match = (expected_set == actual_set)
    
    return precision, recall, f1, exact_match

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
    
    # Exponential backoff: Initial 1s, double it, 6 times max
    # Sequence: 1, 2, 4, 8, 16, 32
    backoff_sequence = [1, 2, 4, 8, 16, 32]
    
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
    parser = argparse.ArgumentParser(description="Evaluate LLM Performer Extraction")
    parser.add_argument("--limit", type=int, default=50, help="Number of samples to test per phase")
    parser.add_argument("--skip-extraction", action="store_true", help="Skip the NO_NAME extraction phase")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, 'docs', 'prompt.config')
    prompts_path = os.path.join(base_dir, 'docs', 'prompts.yaml')
    input_csv = os.path.join(base_dir, 'extracted.csv')
    
    results_dir = os.path.join(base_dir, 'test', 'results')
    os.makedirs(results_dir, exist_ok=True)
    output_jsonl = os.path.join(results_dir, 'multi_model_test_results.jsonl')
    
    config = load_config(config_path)
    prompts = load_prompts(prompts_path)
    
    # Models to test - now from config
    models_raw = config.get('MODELS', '')
    if models_raw:
        models = [m.strip() for m in models_raw.split(',') if m.strip()]
    else:
        # Fallback if config is missing the key
        models = [config.get('OPENAI_MODEL', 'ollama@gemma3:1b')]
    
    print(f"Starting Multi-Model Evaluation...")
    print(f"Models: {models}")
    print(f"Prompts: {[p['id'] for p in prompts]}")
    print(f"Limit: {args.limit}")
    print()

    # Load data
    try:
        df = pd.read_csv(input_csv)
    except Exception as e:
        print(f"Error reading {input_csv}: {e}")
        return

    # Split data
    # Normalize 'performers' column to handle NaN
    df['performers'] = df['performers'].fillna('')
    
    # Validation Set: Has content in performers and not NO_NAME
    validation_df = df[
        (df['performers'].str.strip() != '') & 
        (df['performers'].str.upper() != 'NO_NAME')
    ].copy()
    
    # Extraction Set: Empty or NO_NAME
    extraction_df = df[
        (df['performers'].str.strip() == '') | 
        (df['performers'].str.upper() == 'NO_NAME')
    ].copy()

    # Limit validation set
    if len(validation_df) > args.limit:
        validation_df = validation_df.head(args.limit)
    
    print(f"Loaded {len(validation_df)} validation titles (Ground Truth available)")
    print(f"Loaded {len(extraction_df)} extraction titles (NO_NAME)")
    print()

    # Generate Report File Path early
    report_filename = f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    # results_dir is already created above
    report_path = os.path.join(results_dir, report_filename)
    print(f"Report file: {report_path}")
    
    # Initialize Report File
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# LLM Performer Extraction Test Report\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Models: {', '.join(models)}\n\n")
        f.write("## 1. Test Execution Log\n\n")
        f.flush()

    # Metrics storage
    # {(model, prompt_id): {'tp': 0, 'fp': 0, 'fn': 0, 'exact': 0, 'total': 0, 'sum_f1': 0.0, 'times': []}}
    metrics = {}
    
    # Detailed results for report
    # List of dicts: {title, model, prompt, expected, actual, is_pass, f1}
    detailed_results = []

    processed = set()
    # Load existing to skip? Maybe better to overwrite for evaluation runs to ensure consistent N
    # But sticking to existing logic of appending to JSONL for history.
    # However, for metrics calculation we need current run stats.
    
    results_count = 0
    
    # Process validation set
    print("=" * 80)
    print("PHASE 1: VALIDATION (Testing against known performers)")
    print("=" * 80)
    
    for idx, row in validation_df.iterrows():
        title = row['title']
        expected = row['performers']
        
        print(f"\nTitle: {title[:70]}...")
        print(f"Expected: {expected}")
        
        title_f1_scores = []
        
        for model in models:
            for p in prompts:
                prompt_id = p['id']
                metric_key = (model, prompt_id)
                if metric_key not in metrics:
                    metrics[metric_key] = {'tp': 0, 'fp': 0, 'fn': 0, 'exact': 0, 'total': 0, 'sum_f1': 0.0, 'times': []}
                
                start_time = time.time()
                output = call_llm(config, model, p['template'], title)
                duration = time.time() - start_time
                
                # Calculate metrics
                prec, rec, f1, is_exact = calculate_metrics(expected, output)
                title_f1_scores.append(f1)
                
                # Add delay between calls to respect rate limits
                time.sleep(3)
                
                # Update stats
                # Re-calculate raw counts for global aggregation
                exp_set = normalize_names(expected, separator=';')
                act_set = normalize_names(output, separator=',')
                tp = len(exp_set.intersection(act_set))
                fp = len(act_set - exp_set)
                fn = len(exp_set - act_set)
                
                metrics[metric_key]['tp'] += tp
                metrics[metric_key]['fp'] += fp
                metrics[metric_key]['fn'] += fn
                metrics[metric_key]['exact'] += 1 if is_exact else 0
                metrics[metric_key]['total'] += 1
                metrics[metric_key]['sum_f1'] += f1
                metrics[metric_key]['times'].append(duration)
                
                # Store detailed result
                detailed_results.append({
                    "title": title,
                    "model": model,
                    "prompt": prompt_id,
                    "expected": expected,
                    "actual": output,
                    "is_pass": is_exact,
                    "f1": f1
                })

                # STREAM TO REPORT FILE
                with open(report_path, 'a', encoding='utf-8') as f:
                    status_icon = "✅ PASS" if is_exact else "❌ FAIL"
                    f.write(f"### {status_icon} | {model} | {prompt_id}\n")
                    f.write(f"- **Title**: {title}\n")
                    f.write(f"- **Expected**: `{expected}`\n")
                    f.write(f"- **Actual**: `{output}`\n")
                    f.write(f"- **F1**: {f1:.2f}\n")
                    f.write("\n---\n\n")
                    f.flush()

                result_entry = {
                    "title": title,
                    "model": model,
                    "prompt_id": prompt_id,
                    "output": output,
                    "expected": expected,
                    "phase": "validation",
                    "timestamp": datetime.now().isoformat(),
                    "precision": prec,
                    "recall": rec,
                    "f1": f1,
                    "exact_match": is_exact,
                    "duration_seconds": duration
                }
                
                # Append result
                with open(output_jsonl, 'a', encoding='utf-8') as fout:
                    fout.write(json.dumps(result_entry) + "\n")
                
                if not output.startswith("ERROR"):
                    results_count += 1
                    status = "✅" if is_exact else "❌"
                    print(f"  [{model}|{prompt_id}] -> {output} {status} (F1: {f1:.2f})")

    # Print Report
    print("\n" + "=" * 80)
    print("EVALUATION REPORT")
    print("=" * 80)
    
    report_data = []
    for (model, prompt_id), stats in metrics.items():
        total = stats['total']
        if total == 0:
            continue
            
        # Micro-averaged metrics over the dataset
        tp = stats['tp']
        fp = stats['fp']
        fn = stats['fn']
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        # Macro F1 (average of individual F1 scores)
        macro_f1 = stats['sum_f1'] / total if total > 0 else 0
        
        accuracy = stats['exact'] / total
        avg_time = sum(stats['times']) / len(stats['times']) if stats['times'] else 0
        
        report_data.append({
            "Model": model,
            "Prompt": prompt_id,
            "Accuracy (Exact)": f"{accuracy:.1%}",
            "F1 (Micro)": f"{f1:.3f}",
            "F1 (Macro)": f"{macro_f1:.3f}",
            "Precision": f"{precision:.3f}",
            "Recall": f"{recall:.3f}",
            "Avg Time (s)": f"{avg_time:.2f}"
        })
    
    # Append Aggregates to Report File
    with open(report_path, 'a', encoding='utf-8') as f:
        f.write("## 2. Performance by Model & Prompt\n\n")
        
        if report_data:
            report_df = pd.DataFrame(report_data)
            print(report_df.to_string(index=False))
            f.write(report_df.to_markdown(index=False))
        else:
            print("No results to report.")
            f.write("No data available.")
        f.write("\n\n")
        
        # Aggregated by Model Report
        print("\n" + "=" * 80)
        print("AGGREGATED MODEL PERFORMANCE (Across all prompts)")
        print("=" * 80)
        
        f.write("## 3. Aggregated Performance by Model\n\n")
        
        # Group metrics by model
        model_metrics = {}
        for (model, prompt_id), stats in metrics.items():
            if model not in model_metrics:
                model_metrics[model] = {'tp': 0, 'fp': 0, 'fn': 0, 'exact': 0, 'total': 0, 'sum_f1': 0.0, 'times': []}
            
            m_stats = model_metrics[model]
            m_stats['tp'] += stats['tp']
            m_stats['fp'] += stats['fp']
            m_stats['fn'] += stats['fn']
            m_stats['exact'] += stats['exact']
            m_stats['total'] += stats['total']
            m_stats['sum_f1'] += stats['sum_f1']
            m_stats['times'].extend(stats['times'])
            
        model_report_data = []
        for model, stats in model_metrics.items():
            total = stats['total']
            if total == 0:
                continue
                
            tp = stats['tp']
            fp = stats['fp']
            fn = stats['fn']
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            macro_f1 = stats['sum_f1'] / total if total > 0 else 0
            accuracy = stats['exact'] / total
            avg_time = sum(stats['times']) / len(stats['times']) if stats['times'] else 0
            
            model_report_data.append({
                "Model": model,
                "Accuracy": f"{accuracy:.1%}",
                "F1 (Micro)": f"{f1:.3f}",
                "F1 (Macro)": f"{macro_f1:.3f}",
                "Avg Time (s)": f"{avg_time:.2f}"
            })
            
        if model_report_data:
            model_df = pd.DataFrame(model_report_data)
            print(model_df.to_string(index=False))
            f.write(model_df.to_markdown(index=False))
        else:
            print("No results to report.")
            f.write("No data available.")
            
    print(f"\nReport generated: {report_filename}")

    if not args.skip_extraction:
        # Process extraction set
        print("\n" + "=" * 80)
        print("PHASE 2: EXTRACTION (Processing NO_NAME titles)")
        print("=" * 80)
        
        # Apply limit to extraction too
        if len(extraction_df) > args.limit:
            extraction_df = extraction_df.head(args.limit)
            
        for idx, row in extraction_df.iterrows():
            title = row['title']
            print(f"\nTitle: {title[:70]}...")
            
            for model in models:
                for p in prompts:
                    prompt_id = p['id']
                    
                    output = call_llm(config, model, p['template'], title)
                    
                    # Add delay between calls to respect rate limits
                    time.sleep(3)
                    
                    result_entry = {
                        "title": title,
                        "model": model,
                        "prompt_id": prompt_id,
                        "output": output,
                        "phase": "extraction",
                        "timestamp": datetime.now().isoformat(),
                        "rating": ""
                    }
                    
                    with open(output_jsonl, 'a', encoding='utf-8') as fout:
                        fout.write(json.dumps(result_entry) + "\n")
                    
                    print(f"  [{model}|{prompt_id}] -> {output}")

    print(f"\n{'=' * 80}")
    print(f"Test session complete. Total successful entries: {results_count}")
    print(f"Results stored in {output_jsonl}")
    print(f"{'=' * 80}")

if __name__ == "__main__":
    main()
