"""Submit the mounted pipeline and fail the Job if its run does not succeed."""
import logging
import os
from pathlib import Path

import kfp
from kfp.client import ServiceAccountTokenVolumeCredentials


def main():
    logging.basicConfig(level=logging.INFO)
    credentials = None
    if os.environ.get("KFP_AUTH_MODE", "none") == "token":
        credentials = ServiceAccountTokenVolumeCredentials(
            path=os.environ["KF_PIPELINES_SA_TOKEN_PATH"]
        )
    client = kfp.Client(
        host=os.environ["KFP_HOST"],
        namespace=os.environ["KFP_NAMESPACE"],
        credentials=credentials,
    )
    revision = Path("/pipeline/revision").read_text().strip()
    run = client.create_run_from_pipeline_package(
        pipeline_file="/pipeline/breast_cancer_pipeline.yaml",
        experiment_name="breast-cancer-gitops",
        run_name=f"breast-cancer-{revision[:12]}",
        namespace=os.environ["KFP_NAMESPACE"],
        enable_caching=False,
    )
    print(f"Submitted run {run.run_id}, source revision {revision}", flush=True)
    completed = client.wait_for_run_completion(
        run_id=run.run_id, timeout=1800, sleep_duration=10
    )
    if str(completed.state).lower() != "succeeded":
        raise RuntimeError(f"Kubeflow run {run.run_id} ended with state {completed.state}")
    print(f"Run {run.run_id} succeeded", flush=True)


if __name__ == "__main__":
    main()
