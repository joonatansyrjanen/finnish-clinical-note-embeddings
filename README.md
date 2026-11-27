# Source or clinical content? 2-D projections of Finnish clinical text embeddings

**CMT paper ID: TODO**

AI in Health Technologies (ELEC-E8739) 2026, course project. 
Alexandra Dahlberg, Heidi Tarkiainen, Joonatan Syrjänen.

Open `project.ipynb` in Colab and select Runtime → Run all. This runs the cells in order using the repository’s synthetic data and saved embeddings. Open `project_realdata_run.ipynb` to view the saved results from the complete run on real data in Acamedic.

## What is in the repo

| Folder or file | What it is |
| --- | --- |
| `project.ipynb` | The whole project: data, embeddings, pictures, kNN agreement, classifiers, results |
| `project_realdata_run.ipynb` | Saved notebook from the real data run in Acamedic |
| `mock_data/` | Synthetic copies of the HUS Acamedic tables, same file names and columns as the real export. `mock_data/README.md` says what we planted in them |
| `embeddings/` | Saved embeddings (no text), so the notebook runs without Ollama |
| `results/` | Saved figures and tables from the synthetic analysis |

## Where each result comes from

Both notebooks use the same section and cell numbers. See project_realdata_run.ipynb for real-data results and project.ipynb for synthetic results. The files listed below contain synthetic results and are in results/bge-m3/.

| Result | Notebook section or cell | Saved output |
| --- | --- | --- |
| Table 1, data summary | 3, In [4] for notes, patients and diagnosis codes, In [5] for imaging counts | Printed in both notebooks |
| 99th percentile of note length and number of notes that reached the 8,192-token limit | 4, In [8] | Printed in both notebooks |
| PCA coloured by every label | 5.1 | `pca.png` |
| t-SNE coloured by every label | 5.2 | `tsne.png` |
| UMAP coloured by every label | 5.3 | `umap.png`, `coordinates.csv` |
| Notes vs imaging texts (Rami-style figure) | 5.4 | `notes_vs_imaging.png` |
| kNN agreement, full space vs pictures | 6, In [15] | `knn_agreement.csv` |
| Notes vs imaging texts, kNN agreement | 6, In [16] | Printed in both notebooks |
| Silhouette scores | 6, In [17] | `silhouette.csv` |
| Classifier training checkpoints | 7, In [20] | `classifier_checkpoints.csv` |
| Classifiers and surface baselines | 7, In [21] | `classifier_auroc.csv`, `classifier_auroc_per_code.csv` |
| Classifiers on doctors' notes only | 7, In [21] | `classifier_auroc_doctors.csv` |
| Q2, picture vs classifier per ICD code | 8, In [22] for the table, In [23] for the figure and correlation | `per_code.csv`, `picture_vs_classifier.png`, correlation printed in both notebooks |
| Seeds and UMAP settings | 9, In [25] for the table, In [26] for the figure | `seeds_and_settings.csv`, `umap_settings.png` |
| Note type and diagnosis mixed up | 10 | `note_type_and_diagnosis_summary.csv` |
| Clusters for the clinical review | 11 | `clusters.png` |

## Contribution statement
 
- **Alexandra Dahlberg:** Worked on TODO. AI tools: TODO (tool, what it was used for), roughly TODO % of this work.
- **Heidi Tarkiainen:** Worked on TODO. AI tools: TODO (tool, what it was used for), roughly TODO % of this work.
- **Joonatan Syrjänen:** Worked on TODO. AI tools: TODO (tool, what it was used for), roughly TODO % of this work.
