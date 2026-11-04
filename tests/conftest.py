"""Shared test helpers: synthetic DICOM files so tests never need real patient data."""

from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid


def write_dicom(
    path: Path,
    pixels: np.ndarray,
    photometric: str = "MONOCHROME2",
    view: str = "PA",
    sex: str = "F",
    age: str = "045Y",
) -> Path:
    """Write a minimal, valid, uncompressed 8-bit grayscale DICOM file.

    Args:
        path: Destination file.
        pixels: 2D array of values 0-255.
        photometric: ``MONOCHROME1`` or ``MONOCHROME2``.
        view: ViewPosition tag value.
        sex: PatientSex tag value.
        age: PatientAge tag value in DICOM ``nnnY`` form.

    Returns:
        The path written.
    """
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "CR"
    ds.ViewPosition = view
    ds.PatientSex = sex
    ds.PatientAge = age
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.astype(np.uint8).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path
