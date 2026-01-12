import pandas as pd
import os

def cleanup_csv(file_path):
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    print(f"Loading {file_path}...")
    try:
        df = pd.read_csv(file_path)
        initial_count = len(df)
        print(f"Initial row count: {initial_count}")

        if 'item_url' not in df.columns:
            print(f"Error: 'item_url' column not found in {file_path}")
            print(f"Columns found: {df.columns.tolist()}")
            return

        # Keep the first occurrence of each item_url
        df_cleaned = df.drop_duplicates(subset=['item_url'], keep='first')
        final_count = len(df_cleaned)
        
        removed_count = initial_count - final_count
        print(f"Final row count: {final_count}")
        print(f"Removed {removed_count} duplicate rows.")

        if removed_count > 0:
            df_cleaned.to_csv(file_path, index=False)
            print(f"Successfully cleaned {file_path}.")
        else:
            print("No duplicates found. File remains unchanged.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    cleanup_csv("extracted.csv")
