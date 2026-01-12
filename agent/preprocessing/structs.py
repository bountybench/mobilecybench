import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Symbol:
    """Code symbol from tree-sitter (class, method, field)."""

    name: str
    type: str  # "class", "method", "field", "interface"
    file_path: str
    line_start: int
    line_end: int
    parent: Optional[str] = None  # Parent class/interface name
    modifiers: List[str] = field(default_factory=list)  # public, private, static, etc.
    parameters: List[str] = field(default_factory=list)  # For methods
    return_type: Optional[str] = None  # For methods/fields

@dataclass
class CodeIndex:
    """App code structure (manifest + tree-sitter)."""

    package_name: str

    # Manifest-level (Android components)
    activities: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    receivers: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    exported_components: List[str] = field(default_factory=list)

    # Code-level (tree-sitter)
    classes: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # class_name -> Symbol dict
    methods: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # method_name -> [Symbol dicts]
    fields: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # field_name -> [Symbol dicts]
    call_graph: Dict[str, List[str]] = field(default_factory=dict)  # caller -> [callees]

    # Sensitive APIs flagged
    sensitive_apis: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    indexed_at: str = ""
    cache_file: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self, filepath: str) -> None:
        """Save CodeIndex to JSON file."""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict (dataclasses.asdict handles nested structures)
        data = asdict(self)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    @staticmethod
    def from_json(filepath: str) -> "CodeIndex":
        """Load CodeIndex from JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)

        return CodeIndex(**data)
