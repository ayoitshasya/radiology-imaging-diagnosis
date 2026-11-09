# Model card: DenseNet121 pneumonia-opacity classifier

**Educational use only. Not for clinical use.** This model is a teaching artefact for a
final-year internship project. It is not a medical device, has not been clinically or
externally validated, and its output is not a diagnosis.

All numbers below are copied from files written by the project's scripts; each table
names its source.

## Intended use

- Demonstrating, in a teaching setting, how an image classifier, a validated decision
  threshold, Grad-CAM explanations, human review and an audit trail fit together.
- Running on the public, anonymised RSNA demo studies shipped with this repository,
  through the review viewer, where every result must be approved or rejected by a
  person and every action is logged.

## Out-of-scope use

- Any clinical use: diagnosis, triage, screening, prioritisation or second reading of
  real patients.
- Images from other hospitals, scanners, populations or protocols, paediatric images,
  lateral views, or anything other than frontal adult chest radiographs like RSNA's.
- Treating the Grad-CAM overlay as a localisation or segmentation of disease.
- Any decision without a human reviewer, or any use with real patient data.

## Data

- **Source:** RSNA Pneumonia Detection Challenge (Kaggle), stage 2 training images and
  `stage_2_train_labels.csv`. A study is labelled 1 when it has at least one
  lung-opacity bounding box, 0 otherwise. One source, one labelling effort.
- **Split:** by patient, 70/15/15 for train, validation and test, stratified on the
  label, seed 42 (`ml/preprocessing/build_dataset.py`). Splitting patients rather than
  images means no patient appears in two splits; in this dataset every patient has one
  image.
- **Preprocessing:** DICOM to 224 by 224 grayscale, repeated to three channels and
  normalised with ImageNet statistics for the pretrained backbone.

Sizes (`reports/preprocessing_summary_full.json`, 26684 images in total):

| Split | Images (= patients) | Positive | Positive rate | AP view: images, positive rate | PA view: images, positive rate |
| --- | --- | --- | --- | --- | --- |
| Train | 18678 | 4208 | 0.2253 | 8533, 0.3822 | 10145, 0.0933 |
| Validation | 4003 | 902 | 0.2253 | 1807, 0.3835 | 2196, 0.0952 |
| Test | 4003 | 902 | 0.2253 | 1833, 0.3873 | 2170, 0.0885 |

## Model and training

- **Architecture:** torchvision DenseNet121 with ImageNet-pretrained weights and a
  single-logit output for pneumonia opacity.
- **Training** (`ml/classification/train.py`, settings in `config.yaml`): AdamW,
  learning rate 1e-4, weight decay 1e-5, batch size 32, gradient clipping at norm 1.0;
  BCE-with-logits loss weighted for class imbalance (pos_weight 3.43869, from
  `reports/training_log.json`); learning rate halved when validation AUROC stops
  improving for 2 epochs; early stopping after 5 epochs without improvement; mixed
  precision on GPU.
- **Augmentation** (training only): small random affine transforms (rotation up to 10
  degrees, shift up to 5 percent, scale 0.95 to 1.05) and brightness and contrast
  jitter of 0.1. No horizontal flip: a flipped chest film puts the heart on the wrong
  side.
- **Run** (`reports/training_log.json`): trained on a GPU in a Kaggle notebook, seed
  42; stopped early after 8 epochs; best epoch 3 with validation AUROC 0.87808, which
  is the checkpoint used (`models/densenet121_best.pt`, versioned with DVC; sha256
  `dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9`).

## Decision threshold

The model outputs a probability; the label is 1 when the probability is at or above the
threshold. The threshold was chosen on the **validation** split by maximising Youden's J
(sensitivity + specificity - 1), never on the test split
(`reports/classification_metrics.json`):

| Threshold | Method | Validation sensitivity | Validation specificity |
| --- | --- | --- | --- |
| 0.480127 | youden_j_on_validation | 0.8104 | 0.7852 |

The backend reads it from that report at startup and refuses to load the model if the
method is anything else.

## Results on the test split

Test split, 4003 studies, 902 positive (`reports/classification_metrics.json`). Values in
brackets are 95% bootstrap confidence intervals over 1000 resamples, seed 42.

| Metric | All test studies (4003) | AP view only (1833) | PA view only (2170) |
| --- | --- | --- | --- |
| AUROC | 0.8847 [0.8725, 0.8963] | 0.8276 [0.8079, 0.8465] | 0.8675 [0.8412, 0.8933] |
| Sensitivity at threshold | 0.8293 [0.8038, 0.8534] | 0.8972 [0.874, 0.9181] | 0.5781 [0.5071, 0.6492] |
| Specificity at threshold | 0.773 [0.7583, 0.7884] | 0.5111 [0.4824, 0.5388] | 0.9216 [0.9099, 0.9339] |
| Precision at threshold | 0.5152 [0.4882, 0.5412] | 0.5371 [0.5104, 0.5649] | 0.4173 [0.3611, 0.4768] |

Baselines on the same test split (`reports/baselines.json`):

| Baseline | Result |
| --- | --- |
| View only: score = training positive rate of the image's view (AP 0.3822, PA 0.0933) | AUROC 0.7125 [0.6959, 0.7273] |
| Majority class (always predict 0) | AUROC 0.5, accuracy 0.7747, sensitivity 0.0 |

The majority-class accuracy shows why accuracy is not reported for the model: predicting
"no opacity" for everyone already scores 0.7747.

## Grad-CAM validation

Grad-CAM is taken from the last dense block (`features.denseblock4`). It was checked
against the RSNA ground-truth boxes on the 748 true-positive test studies that have
boxes (`reports/gradcam_localisation.json`; 95% bootstrap intervals). A uniform heatmap
scores the box's share of the image (mean 0.14), so it is the chance level.

| Heatmap | Share of heatmap mass inside the boxes | Pointing game (peak inside a box) |
| --- | --- | --- |
| Trained model | 0.2632 [0.2518, 0.2745] | 0.377 [0.3422, 0.4118] |
| Uniform (chance) | 0.14 [0.1328, 0.1474] | 0.14 [0.1328, 0.1474] |
| Random-init model | 0.1185 [0.1112, 0.1253] | 0.0749 [0.0561, 0.0936] |

Paired per image, the trained model's mass inside the boxes was higher than uniform by
0.1232 [0.1179, 0.1282] on average, and higher on a share of 0.9505 of the images. By
view: AP (637 studies) trained mass 0.2712 against uniform 0.1484; PA (111 studies)
0.2171 against 0.0914; pointing game 0.3815 (AP) and 0.3514 (PA).

So the heatmaps lean towards the annotated regions more than chance and more than an
untrained network, but most of their mass still falls outside the boxes, and the peak
lands inside a box in fewer than half of the images.

## Limitations

- **AP/PA view confound.** Positive rates differ sharply by view (training: AP 0.3822,
  PA 0.0933), and a baseline that knows only the view position reaches AUROC 0.7125.
  Part of the model's score can therefore follow the view rather than the lungs. This
  is measured and reported, not removed; per-view
  results above show the trade-off (AP: high sensitivity, low specificity; PA: the
  reverse).
- **Single-source data.** All images and labels come from one public dataset and one
  labelling effort; performance on other hospitals, scanners or populations is unknown.
- **No external validation.** The only evaluation is on a held-out split of the same
  dataset. There is no external test set and no prospective or clinical study.
- **Coarse Grad-CAM.** The heatmap comes from a 7 by 7 feature map upsampled to 224 by
  224, so it cannot outline lesions; it can also react to markers, borders and
  positioning, which the viewer states in its caption.
- **One study analysed at a time.** Prediction and Grad-CAM run under a single lock in
  one CPU process, so concurrent requests queue. Fine for a demo, not for throughput.
- **List-and-diff sync with Orthanc.** The backend learns about studies by listing
  Orthanc and comparing with Postgres when sync is called; there is no push
  notification, so a newly uploaded study appears only after the next sync.
- **Not for clinical use.** Nothing here has been validated, approved or tested for
  clinical safety. Use only the public demo data.
