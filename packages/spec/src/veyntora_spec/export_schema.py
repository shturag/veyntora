"""Write the JSON Schema that the TS types are generated from.

Usage: python -m veyntora_spec.export_schema <output.json>
"""

import json
import sys
from pathlib import Path

from veyntora_spec.pipeline import PipelineSpec


def main() -> None:
    out = Path(sys.argv[1])
    schema = PipelineSpec.model_json_schema(mode="serialization")
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
