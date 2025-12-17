import os
import sys

from dotenv import load_dotenv

sys.path.append(os.getcwd())
from agent import preprocessing


def main():
    load_dotenv(override=True)
    # Target App
    app_path = "apps/conversations"
    print(f"Running Indexer on {app_path}")

    # tree-sitter (Java/Kotlin) -> call graph, AST
    # vector embedding (all files)
    code_index = preprocessing.index_codebase(app_path)
    
    print(f"Package: {code_index.package_name}")
    print(f"Classes: {len(code_index.classes)}")
    print(f"Methods: {len(code_index.methods)}")

    print("\nTesting Vector Search")
    store = preprocessing.get_vector_store()
    
    query = "omemo encryption"
    print(f"Searching for: {query}")
    
    results = store.search(query, limit=3)
    
    for i, res in enumerate(results):
        print(f"\nResult {i+1}")
        print(f"File: {res.get('file_path')}")
        print(f"Type: {res.get('type')}")
        preview = res.get('text', '')[:80].replace('\n', ' ')
        print(f"Preview: {preview}...")

if __name__ == "__main__":
    main()
