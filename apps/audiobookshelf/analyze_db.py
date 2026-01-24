#!/usr/bin/env python3
"""Analyze audiobookshelf database structure for exploit development."""
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "dbs", "absdatabase-base.sqlite")

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print("=== TABLES ===")
    for t in tables:
        print(f"  - {t}")
    
    # Show libraryItems schema
    if 'libraryItems' in tables:
        cursor.execute("PRAGMA table_info(libraryItems)")
        columns = cursor.fetchall()
        print("\n=== libraryItems columns ===")
        for col in columns:
            print(f"  {col[1]}: {col[2]}")
        
        col_names = [c[1] for c in columns]
        
        # Get sample data and look for relPath in any column
        cursor.execute("SELECT * FROM libraryItems LIMIT 1")
        row = cursor.fetchone()
        if row:
            print("\n=== Searching for relPath in libraryItems ===")
            for i, col in enumerate(columns):
                val = row[i]
                if isinstance(val, str) and 'relPath' in val:
                    print(f"\nColumn '{col[1]}' contains relPath:")
                    try:
                        data = json.loads(val)
                        print(json.dumps(data, indent=2)[:3000])
                    except:
                        print(val[:1000])
    
    # Check books table
    if 'books' in tables:
        cursor.execute("PRAGMA table_info(books)")
        columns = cursor.fetchall()
        print("\n=== books columns ===")
        for col in columns:
            print(f"  {col[1]}: {col[2]}")
        
        cursor.execute("SELECT * FROM books LIMIT 1")
        row = cursor.fetchone()
        if row:
            print("\n=== Searching for relPath in books ===")
            for i, col in enumerate(columns):
                val = row[i]
                if isinstance(val, str) and ('audioFiles' in val or 'relPath' in val):
                    print(f"\nColumn '{col[1]}' contains audioFiles/relPath:")
                    try:
                        data = json.loads(val)
                        print(json.dumps(data, indent=2)[:3000])
                    except:
                        print(val[:1000])
    
    conn.close()

if __name__ == "__main__":
    main()
