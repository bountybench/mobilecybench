import sqlite3
import json

conn = sqlite3.connect('dbs/absdatabase-base.sqlite')
cursor = conn.cursor()

# Get libraryItems columns
cursor.execute('PRAGMA table_info(libraryItems)')
li_cols = [c[1] for c in cursor.fetchall()]
print('libraryItems columns:', li_cols)

# Get books columns
cursor.execute('PRAGMA table_info(books)')
books_cols = [c[1] for c in cursor.fetchall()]
print('books columns:', books_cols)

# Check if audioFiles is in books
cursor.execute('SELECT * FROM books LIMIT 1')
row = cursor.fetchone()
if row:
    for i, col in enumerate(books_cols):
        val = row[i]
        if isinstance(val, str) and 'relPath' in val:
            print(f'\nFound relPath in books.{col}:')
            try:
                data = json.loads(val)
                # Print structure
                if isinstance(data, list) and len(data) > 0:
                    print(f'  Type: list with {len(data)} items')
                    print(f'  First item keys: {list(data[0].keys()) if isinstance(data[0], dict) else "not dict"}')
                elif isinstance(data, dict):
                    print(f'  Keys: {list(data.keys())}')
            except:
                print(f'  Raw value (first 500 chars): {val[:500]}')

# Check libraryItems for mediaId or similar
cursor.execute('SELECT * FROM libraryItems LIMIT 1')
row = cursor.fetchone()
if row:
    print('\nlibraryItems sample:')
    for i, col in enumerate(li_cols):
        val = row[i]
        if val and len(str(val)) < 100:
            print(f'  {col}: {val}')
        elif val:
            print(f'  {col}: (length {len(str(val))})')

conn.close()
