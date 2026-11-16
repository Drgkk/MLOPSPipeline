"""Package compiled KFP IR as a Kubernetes ConfigMap (no cluster access)."""
import os
from pathlib import Path
import subprocess

import yaml
from kfp import compiler

from breast_cancer_pipeline import breast_cancer_pipeline


def main():
    root = Path(__file__).resolve().parents[1]
    revision = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    # Compile to /tmp rather than modifying the user's existing compiled file.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        package = Path(directory) / "pipeline.yaml"
        compiler.Compiler().compile(
            pipeline_func=breast_cancer_pipeline, package_path=str(package)
        )
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "breast-cancer-pipeline"},
            "data": {
                "breast_cancer_pipeline.yaml": package.read_text(),
                "submit_pipeline.py": (root / "submit_pipeline.py").read_text(),
                "revision": revision,
            },
        }
    if sum(len(value.encode()) for value in manifest["data"].values()) >= 1_000_000:
        raise ValueError("Pipeline is too large for this ConfigMap-based lab setup")
    destination = root / "deploy" / "pipeline-configmap.yaml"
    destination.write_text(yaml.safe_dump(manifest, sort_keys=False))
    print(f"Generated {destination} for {revision}")


if __name__ == "__main__":
    main()
