from kfp import compiler, dsl
from kfp.dsl import ClassificationMetrics, Dataset, Input, Metrics, Model, Output


BASE_IMAGE = "python:3.11-slim"
PACKAGES = ["pandas==2.2.3", "scikit-learn==1.6.1", "joblib==1.4.2"]


@dsl.component(base_image=BASE_IMAGE, packages_to_install=PACKAGES)
def import_dataset(dataset: Output[Dataset]):
    from sklearn.datasets import load_breast_cancer

    data = load_breast_cancer(as_frame=True)
    data.frame.to_csv(dataset.path, index=False)
    dataset.metadata["rows"] = int(len(data.frame))
    dataset.metadata["target_names"] = data.target_names.tolist()


@dsl.component(base_image=BASE_IMAGE, packages_to_install=PACKAGES)
def preprocess_and_split(
    dataset: Input[Dataset],
    train_dataset: Output[Dataset],
    test_dataset: Output[Dataset],
    test_size: float,
    random_state: int,
):
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import train_test_split

    if not 0.0 < test_size < 1.0:
        raise ValueError("test_size must be between 0 and 1.")

    frame = pd.read_csv(dataset.path)
    original_rows = len(frame)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna().drop_duplicates()
    if frame.empty or frame["target"].nunique() != 2:
        raise ValueError("Cleaned dataset must contain both target classes.")

    train, test = train_test_split(
        frame,
        test_size=test_size,
        random_state=random_state,
        stratify=frame["target"],
    )
    
    for artifact, split in [(train_dataset, train), (test_dataset, test)]:
        split.to_csv(artifact.path, index=False)
        artifact.metadata["rows"] = int(len(split))
        artifact.metadata["removed_rows"] = int(original_rows - len(frame))
    print(f"Cleaned {original_rows} -> {len(frame)} rows; train={len(train)}, test={len(test)}")


@dsl.component(base_image=BASE_IMAGE, packages_to_install=PACKAGES)
def train_model(
    train_dataset: Input[Dataset],
    model: Output[Model],
    max_depth: int,
    random_state: int,
):
    import joblib
    import pandas as pd
    from sklearn.tree import DecisionTreeClassifier

    train = pd.read_csv(train_dataset.path)
    classifier = DecisionTreeClassifier(max_depth=max_depth, random_state=random_state)
    classifier.fit(train.drop(columns=["target"]), train["target"])
    joblib.dump(classifier, model.path)
    model.metadata["framework"] = "scikit-learn"
    model.metadata["model_type"] = "DecisionTreeClassifier"
    model.metadata["max_depth"] = max_depth


@dsl.component(base_image=BASE_IMAGE, packages_to_install=PACKAGES)
def evaluate_model(
    test_dataset: Input[Dataset],
    model: Input[Model],
    metrics: Output[Metrics],
    confusion_matrix: Output[ClassificationMetrics],
):
    """Evaluate held-out data; malignant (sklearn label 0) is the positive class."""
    import joblib
    import pandas as pd
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix as calculate_confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    test = pd.read_csv(test_dataset.path)
    features, target = test.drop(columns=["target"]), test["target"]
    classifier = joblib.load(model.path)
    predictions = classifier.predict(features)
    malignant_index = list(classifier.classes_).index(0)
    malignant_probability = classifier.predict_proba(features)[:, malignant_index]

    scores = {
        "accuracy": accuracy_score(target, predictions),
        "precision_malignant": precision_score(target, predictions, pos_label=0, zero_division=0),
        "recall_malignant": recall_score(target, predictions, pos_label=0, zero_division=0),
        "f1_malignant": f1_score(target, predictions, pos_label=0, zero_division=0),
        "roc_auc_malignant": roc_auc_score(target == 0, malignant_probability),
    }
    for name, value in scores.items():
        metrics.log_metric(name, float(value))
    confusion_matrix.log_confusion_matrix(
        categories=["malignant", "benign"],
        matrix=calculate_confusion_matrix(target, predictions, labels=[0, 1]).tolist(),
    )
    print(classification_report(target, predictions, labels=[0, 1],
                                target_names=["malignant", "benign"], zero_division=0))
    print(scores)


@dsl.pipeline(
    name="breast-cancer-decision-tree",
    description="Load, clean, split, train and evaluate sklearn's breast cancer dataset.",
)
def breast_cancer_pipeline(
    test_size: float = 0.2,
    random_state: int = 42,
    max_depth: int = 5,
):
    imported = import_dataset()
    prepared = preprocess_and_split(
        dataset=imported.outputs["dataset"],
        test_size=test_size,
        random_state=random_state,
    )
    trained = train_model(
        train_dataset=prepared.outputs["train_dataset"],
        max_depth=max_depth,
        random_state=random_state,
    )
    evaluate_model(
        test_dataset=prepared.outputs["test_dataset"],
        model=trained.outputs["model"],
    )


if __name__ == "__main__":
    from pathlib import Path

    output = Path(__file__).with_suffix(".yaml")
    compiler.Compiler().compile(pipeline_func=breast_cancer_pipeline, package_path=str(output))
    print(f"Compiled pipeline: {output}")
