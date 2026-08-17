# -*- coding: utf-8 -*-
"""
Benchmark Test Script
- Reads fewShotSample_251230.xlsx
- Column A: User Query
- Column B: Gold Answer (SQL)
- Runs Text2SqlUserAgent.main() 3 times for each query.
"""

import os
import sys
import pandas as pd
import time
from Text2SqlUserAgent import main as run_pipeline

# File Path
EXCEL_PATH = r"fewShotSample_251230.xlsx"

def run_benchmark():
    if not os.path.exists(EXCEL_PATH):
        print(f"[Error] Excel file not found: {EXCEL_PATH}")
        return

    # Load Excel
    print(f"[Info] Loading benchmark data from: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH)

    # Assume Column 0 is Query, Column 1 is Gold Answer
    # Let's be safe and use column indices if names are not fixed
    queries = df.iloc[:, 0].tolist()
    gold_answers = df.iloc[:, 1].tolist()

    total_rows = len(queries)
    print(f"[Info] Found {total_rows} samples. Starting benchmark (3 runs each)...")

    for i in range(total_rows):
        query = queries[i]
        gold = gold_answers[i]
        
        if pd.isna(query):
            continue

        print(f"\n" + "="*50)
        print(f" [Sample {i+1}/{total_rows}]")
        print(f" Query: {query}")
        print(f" Gold: {gold}")
        print("="*50)

        for attempt in range(1, 4):
            print(f"\n >>> Attempt {attempt}/3 starting...")
            try:
                # We call the main function directly to avoid subprocess overhead and capture logs in the same DB context
                run_pipeline(user_query=str(query), gold_answer=str(gold) if pd.notna(gold) else None)
                print(f" >>> Attempt {attempt}/3 finished successfully.")
            except Exception as e:
                print(f" [!] Attempt {attempt}/3 failed: {str(e)}")
            
            # Optional: Sleep a bit between runs if needed
            time.sleep(1)

    print("\nBenchmark complete.")

if __name__ == "__main__":
    run_benchmark()
