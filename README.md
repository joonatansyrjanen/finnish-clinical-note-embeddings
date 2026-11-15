# Source or clinical content? 2-D projections of Finnish clinical text embeddings

AI in Health Technologies 2026, course project.
Alexandra Dahlberg, Heidi Tarkiainen, Joonatan Syrjänen.

Everything is in one notebook, `project.ipynb`, which runs from top to bottom. The outputs of a full run on the synthetic data are kept in the notebook.

## What is in the repo

| Folder or file | What it is |
| --- | --- |
| `project.ipynb` | The whole project: data, embeddings, pictures, kNN agreement, classifiers, results |
| `mock_data/` | Synthetic copies of the HUS Acamedic tables, same file names and columns as the real export. `mock_data/README.md` says what we planted in them |
| `embeddings/` | Saved embeddings (no text), so the notebook runs without Ollama |
| `results/` | Every figure and table the notebook saves |

## Where each result comes from

| Result | Notebook section | File in `results/bge-m3/` |
| --- | --- | --- |
| Table 1, data summary | 3 | printed in the notebook |
| Notes over 512 tokens | 4 | printed in the notebook |
| PCA coloured by every label | 5.1 | `pca.png` |
| t-SNE coloured by every label | 5.2 | `tsne.png` |
| UMAP coloured by every label | 5.3 | `umap.png`, `coordinates.csv` |
| Notes vs imaging texts (Rami-style figure) | 5.4 | `notes_vs_imaging.png` |
| kNN agreement, full space vs pictures | 6 | `knn_agreement.csv` |
| Silhouette scores | 6 | `silhouette.csv` |
| Notes vs imaging texts, kNN agreement | 6 | printed in the notebook |
| Classifiers and surface baselines | 7 | `classifier_auroc.csv`, `classifier_auroc_per_code.csv` |
| Q2, picture vs classifier per ICD code | 8 | `per_code.csv`, `picture_vs_classifier.png` |
| Seeds and UMAP settings | 9 | `seeds_and_settings.csv`, `umap_settings.png` |
| Note type and diagnosis mixed up | 10 | `note_type_and_diagnosis.csv` |
| FinBERT layers (real data) | 11 | `finbert_layers.png` |
| Clusters for the clinical review | 12 | `clusters.png` |
