
from dataclasses import asdict
from datetime import datetime
from typing import Dict, List

from agent.custom_agent_v2.shared_knowledge import CodeIndex
from agent.preprocessing.embedding_indexer import embed_files_to_vector_store
from agent.preprocessing.manifest_manager import get_manifests
from agent.preprocessing.source_manager import get_source_files
from agent.preprocessing.tree_sitter_indexer import CodebaseIndexer
from utils.logger import logger


def index_codebase(app_path: str) -> CodeIndex:
    """
    Main entry point for robust app indexing.
    
    Orchestrates:
    1. Manifest Manager: Get package name, components.
    2. Source Manager: Get Java/Kt files, Polyglot files, Resources.
    3. Tree-sitter: Build Call Graph & Structure (Java/Kt only).
    4. Embedding Indexer: Send ALL files (Java/Kt/Polyglot) to Vector Store.
    
    Args:
        app_path: Root of apps/<app-name>
    """
    logger.info("="*60)
    logger.info(f"STARTING INDEXER for {app_path}")
    logger.info("="*60)
    
    # 1. Manifest Discovery
    manifest_info = get_manifests(app_path)
    package_name = manifest_info["package_name"]
    logger.info(f"Package Name: {package_name}")
    
    # Check Cache
    cache_file = f"cache/{package_name}_index.json"
    if _is_cache_fresh(cache_file, app_path):
        logger.info(f"Loading fresh index from {cache_file}")
        return CodeIndex.from_json(cache_file)

    # 2. Source Discovery
    sources = get_source_files(app_path)
    
    # 3. Tree-sitter Indexing (Structure)
    # Only for Java/Kotlin files
    logger.info("Building Structural Index (Java/Kotlin)...")
    indexer = CodebaseIndexer()
    
    total_symbols = 0
    for file_path in sources["java_kotlin_files"]:
        # Index file
        count = indexer.index_file(file_path)
        total_symbols += count
        
    logger.info(f"Structural Index Logic Complete. {total_symbols} symbols found.")

    # 4. Vector Embedding (RAG)
    # We send EVERYTHING: Java/Kt source + Polyglot files
    all_files_for_rag = sources["java_kotlin_files"] + sources["polyglot_files"] + sources["resource_files"]
    logger.info(f"Generating Embeddings for {len(all_files_for_rag)} files...")
    
    try:
        embed_files_to_vector_store(all_files_for_rag, indexer=indexer)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")

    # 5. Build Final CodeIndex Object
    # Extract component lists from manifest_data
    m_data = manifest_info.get("manifest_data", {})
    
    # Flag sensitive APIs
    logger.info("Flagging sensitive APIs...")
    sensitive_apis = flag_sensitive_apis(indexer)
    logger.info(f"Found {len(sensitive_apis)} sensitive API calls")

    code_index = CodeIndex(
        package_name=package_name,
        activities=m_data.get("activities", []),
        services=m_data.get("services", []),
        receivers=m_data.get("receivers", []),
        providers=m_data.get("providers", []),
        permissions=m_data.get("permissions", []),
        exported_components=m_data.get("exported_components", []),
        
        # Convert Symbols to dicts
        classes={name: asdict(s) for name, s in indexer.classes.items()},
        methods={name: [asdict(s) for s in syms] for name, syms in indexer.methods.items()},
        fields={name: [asdict(s) for s in syms] for name, syms in indexer.fields.items()},
        call_graph=indexer.call_graph,
        
        sensitive_apis=sensitive_apis,
        
        indexed_at=datetime.now().isoformat(),
        cache_file=cache_file
    )

    # Save
    code_index.to_json(cache_file)
    logger.info(f"Index saved to {cache_file}")
    
    return code_index

def flag_sensitive_apis(indexer: CodebaseIndexer) -> List[Dict]:
    """
    Flag sensitive API calls in indexed code.
    """
    sensitive_patterns = {
        "webview": [
            "loadUrl", "evaluateJavascript", "addJavascriptInterface", "setWebViewClient", 
            "setWebChromeClient", "loadData", "loadDataWithBaseURL"
        ],
        "runtime": ["Runtime.exec", "ProcessBuilder", "Runtime.getRuntime"],
        "sql": ["rawQuery", "execSQL", "SQLiteDatabase.query", "compileStatement", "query"],
        "crypto": ["Cipher.getInstance", "MessageDigest.getInstance", "SecretKey", "KeyGenerator", "Mac.getInstance"],
        "network": ["HttpURLConnection", "OkHttpClient", "HttpClient", "URLConnection.openConnection", "Retrofit"],
        "file": ["FileInputStream", "FileOutputStream", "openFileOutput", "openFileInput", "File(", "createTempFile"],
        "intent_sink": ["startActivity", "sendBroadcast", "startService", "startActivityForResult"],
        "reflection": ["Class.forName", "Method.invoke", "getDeclaredMethod"],
        "intent_source": ["getIntent", "getStringExtra", "getIntExtra", "getBooleanExtra", "getBundleExtra", "getExtras", "getData"],
        "deeplink": ["getQueryParameter", "getPathSegments", "getHost", "getScheme", "getDataString"],
        "provider_source": ["query", "insert", "update", "delete", "openFile"],
        "broadcast_source": ["onReceive", "getResultData", "getOrderedHint"],
        "ipc": ["Binder", "Messenger", "IBinder", "ServiceConnection", "onBind"],
        "storage": ["getSharedPreferences", "getExternalStorageDirectory", "getExternalFilesDir", "MODE_WORLD_READABLE", "MODE_WORLD_WRITEABLE"],
        "js_bridge": ["@JavascriptInterface", "addJavascriptInterface", "onJsAlert", "onJsPrompt"],
    }

    sensitive_apis = []

    # Search through all methods
    for method_name, symbols in indexer.methods.items():
        for symbol in symbols:
            # Check if method name matches sensitive patterns
            for category, patterns in sensitive_patterns.items():
                for pattern in patterns:
                    if pattern.lower() in symbol.name.lower():
                        sensitive_apis.append(
                            {
                                "class": symbol.parent or "unknown",
                                "method": symbol.name,
                                "api_call": pattern,
                                "category": category,
                                "line": symbol.line_start,
                                "file": symbol.file_path,
                            }
                        )

    return sensitive_apis

def _is_cache_fresh(cache_file: str, app_path: str) -> bool:
    # TODO: for now, always refresh for testing
    return False
