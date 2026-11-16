# Local Kubeflow + Argo CD CI/CD

All compilation runs on your self-hosted GitHub runner. Argo CD and training run
in Minikube. GitHub stores Git and coordinates the runner; no cloud deployment
or container registry is required.

## Before the first push

1. Keep the self-hosted runner online. It needs `python3`, Python's `venv` module,
   Git and internet access. The workflow uses its own `.venv`, not `path/to/venv`.
2. In GitHub repository Settings → Actions → General → Workflow permissions,
   allow read and write permissions if repository policy requires it. The workflow
   requests `contents: write` to push generated manifests. Branch protection must
   permit this bot push for this simple lab design.
3. Set `repoURL` in `argocd/application.yaml` to your repository's HTTPS URL.
   The files target `master`, matching this checkout. If your remote branch is
   `main`, change both the workflow's push branch and the Application revision.
4. Check your installation from a terminal with cluster access:

   ```bash
   kubectl get svc -n kubeflow ml-pipeline-ui
   kubectl -n kubeflow get deployment ml-pipeline -o yaml
   kubectl get profiles
   ```

   Defaults assume **standalone Pipelines**, with namespace `kubeflow`, no token
   authentication, and the internal `ml-pipeline-ui` endpoint. Check `MULTIUSER` in
   the deployment. A missing Profiles CRD is normal for standalone Pipelines.
   For full Kubeflow, follow the multi-user section below before syncing.
5. Add a remote if none exists:

   ```bash
   git remote add origin https://github.com/YOUR_USER/YOUR_REPOSITORY.git
   ```

6. Commit and push the project files (do not add your virtual environment or runner):

   ```bash
   git add .gitignore .github requirements-ci.txt breast_cancer_pipeline.py submit_pipeline.py scripts deploy argocd README.md
   git commit -m "Add local Kubeflow GitOps CI/CD"
   git push -u origin master
   ```

7. In GitHub Actions, wait for **Compile and publish pipeline manifests** to pass.
   It commits `deploy/pipeline-configmap.yaml`, including the source commit SHA.
   This workflow only generates files and pushes Git; it does not need kubeconfig
   or kubectl. A failed compilation cannot publish a deployment update.
8. Bootstrap Argo CD after that CI run passes:

   ```bash
   kubectl apply -f argocd/application.yaml
   kubectl -n argocd port-forward svc/argocd-server 8081:443
   ```

   Open https://localhost:8081 and select `breast-cancer-mlops`. Private Git
   repositories need repository credentials configured in Argo CD Settings.
   Argo CD polls Git; use Refresh to speed up detection. Use a full application
   sync: selective resource sync does not run hooks.

## Observe the first run

```bash
kubectl -n kubeflow get jobs,pods
kubectl -n kubeflow logs -f job/submit-breast-cancer-pipeline
```

The PostSync Job installs KFP, submits the mounted compiled pipeline, prints its
run ID and source revision, and waits up to 30 minutes. A failed KFP run explicitly
fails the Job. Check the experiment `breast-cancer-gitops` in Kubeflow.

The last Job remains for inspecting logs and is replaced on the next sync.
Syncing manually triggers another run too. Jobs are not automatically retried:
this avoids a retry silently submitting another training run. A timeout or lost
connection can leave a training run active; inspect Kubeflow before retrying.

Argo CD manages only `deploy/`, not your Kubeflow installation. The compiled
pipeline is stored inside a ConfigMap; it is **not** applied as a Kubernetes
resource itself. This packaging is suitable for this small lab pipeline.

## Demonstrate a code change

Pull the generated bot commit before making your next push:

```bash
git pull --ff-only
```

In `breast_cancer_pipeline.py`, change the pipeline parameter default from
`max_depth: int = 5` to `max_depth: int = 2`. Then:

```bash
git add breast_cancer_pipeline.py
git commit -m "Train a shallower decision tree"
git push
```

Watch CI pass, its generated commit appear, Argo CD sync, and a new Kubeflow run
execute. Caching is disabled for this demonstration. Compare malignant recall,
F1, accuracy and the confusion matrix. Better scores are not guaranteed.

For the failure demonstration, push a syntax error: CI fails and does not publish
an updated ConfigMap. Fix the error afterward. Compilation validates the pipeline
graph, not the actual model execution; runtime failures appear in the Job/KFP run.

## Full Kubeflow / multi-user installations

Use your existing Kubeflow **profile namespace** (the namespace selected in the
Kubeflow UI). Do not create an arbitrary namespace instead.

- Set `spec.destination.namespace` in `argocd/application.yaml` to that profile.
- Set `KFP_NAMESPACE` in `deploy/settings.yaml` to the same profile.
- Keep `KFP_HOST` pointing at the Pipelines service in the installation namespace.
- Set `KFP_AUTH_MODE: token` in `deploy/settings.yaml`.
- Add `serviceAccountName: default-editor` under the Job's `template.spec`, if
  that existing profile account has Pipelines edit permissions. Verify it exists
  with `kubectl -n YOUR_PROFILE get sa default-editor`.
- Add this item to the container's `volumeMounts`:

  ```yaml
  - name: kfp-token
    mountPath: /var/run/secrets/kubeflow/pipelines
    readOnly: true
  ```

- Add this item to the pod's `volumes`:

  ```yaml
  - name: kfp-token
    projected:
      sources:
        - serviceAccountToken:
            path: token
            audience: pipelines.kubeflow.org
            expirationSeconds: 3600
  ```

Commit those changes before bootstrapping. On an already bootstrapped app, a push
to `deploy/` may sync immediately, before CI; keep compiled source publication in
the CI-generated ConfigMap. Cluster-specific Istio/network policies may also need
to permit this profile workload to reach the API. Do not disable authentication
to work around a 401/403.

Official connection instructions:
https://www.kubeflow.org/docs/components/pipelines/user-guides/core-functions/connect-api/

## Common issues

- **Runner stays idle:** confirm it has `self-hosted`, `linux`, `x64` labels and
  the workflow was pushed to `master`. For ARM hardware change `x64` to `ARM64`.
- **Bot push gets 403:** check Actions write permission and branch protection.
- **Argo CD cannot read Git:** check repository URL, revision and credentials.
- **Job gets 401/403:** use the multi-user configuration and verify account access.
- **Job gets connection refused/404:** verify `ml-pipeline-ui` service and endpoint.
- **Job cannot install KFP:** the pod needs internet access for PyPI dependencies.
- **Source push rejected:** `git pull --ff-only` first to include the bot commit.
- **Newer push arrives during CI:** the stale run skips publishing; the newer
  queued run publishes instead. A push racing the final bot push fails visibly;
  rerun the workflow on the latest branch revision.
