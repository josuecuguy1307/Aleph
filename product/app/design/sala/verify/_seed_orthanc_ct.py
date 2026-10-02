#!/usr/bin/env python3
"""_seed_orthanc_ct.py — siembra en Orthanc el volumen CT de tórax SINTÉTICO que usa el
héroe de medicina (R4). Idempotente: si ya hay una serie CT con ≥20 cortes, no hace nada.

Geometría por corte (128×128, axial): elipse de tejido blando (~+40 HU) + dos pulmones
de aire (~-800 HU) + vértebra de hueso (~+700 HU). HU válidos para los umbrales de
segmentacion_server (lung/bone) y con la metadata que _load_volume exige (RescaleSlope/
Intercept, PixelSpacing, ImagePositionPatient con z creciente, misma SeriesInstanceUID).

Uso: <python-con-pydicom> _seed_orthanc_ct.py   (ORTHANC_URL opcional, default :8042)
"""
import io
import os
import sys

import numpy as np
import pydicom
import requests
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

ORTHANC = os.environ.get("ORTHANC_URL", "http://127.0.0.1:8042")
N_SLICES, SIZE = 40, 128

def _existing_ct_ok() -> bool:
    try:
        for sid in requests.get(f"{ORTHANC}/series", timeout=5).json():
            s = requests.get(f"{ORTHANC}/series/{sid}", timeout=5).json()
            if s.get("MainDicomTags", {}).get("Modality") == "CT" and len(s.get("Instances", [])) >= 20:
                return True
    except Exception:
        pass
    return False

def _slice_hu(k: int) -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    cx = cy = SIZE / 2
    hu = np.full((SIZE, SIZE), -1000.0)                    # aire ambiente
    body = ((x - cx) / 52) ** 2 + ((y - cy) / 44) ** 2 <= 1
    hu[body] = 40.0                                        # tejido blando
    t = k / max(1, N_SLICES - 1)
    lung_r = 0.55 + 0.35 * np.sin(np.pi * t)               # pulmones crecen y decrecen en z
    for sx in (-1, 1):
        lx = cx + sx * 22
        lung = ((x - lx) / (16 * lung_r + 1e-6)) ** 2 + ((y - (cy - 4)) / (26 * lung_r + 1e-6)) ** 2 <= 1
        hu[lung & body] = -800.0                           # aire pulmonar
    spine = (x - cx) ** 2 + (y - (cy + 30)) ** 2 <= 7 ** 2
    hu[spine] = 700.0                                      # hueso
    return hu

def main() -> int:
    if _existing_ct_ok():
        print("orthanc ya tiene un volumen CT ≥20 cortes — no siembro")
        return 0
    study_uid, series_uid, frame_uid = generate_uid(), generate_uid(), generate_uid()
    for k in range(N_SLICES):
        hu = _slice_hu(k)
        pixels = np.clip(hu + 1024.0, 0, 4095).astype(np.uint16)  # intercept -1024

        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian

        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID = meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
        ds.FrameOfReferenceUID = frame_uid
        ds.Modality, ds.PatientName, ds.PatientID = "CT", "SINTETICO^TORAX", "QA-SALA-CT"
        ds.StudyDescription, ds.SeriesDescription = "CT torax sintetico (dev/test)", "axial"
        ds.InstanceNumber, ds.SeriesNumber = k + 1, 1
        ds.ImagePositionPatient = [0.0, 0.0, float(k) * 2.5]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing, ds.SliceThickness = [2.0, 2.0], 2.5
        ds.Rows = ds.Columns = SIZE
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
        ds.SamplesPerPixel, ds.PixelRepresentation = 1, 0
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleSlope, ds.RescaleIntercept = 1.0, -1024.0
        ds.PixelData = pixels.tobytes()

        buf = io.BytesIO()
        pydicom.dcmwrite(buf, ds, enforce_file_format=True)
        r = requests.post(f"{ORTHANC}/instances", data=buf.getvalue(),
                          headers={"Content-Type": "application/dicom"}, timeout=10)
        r.raise_for_status()
    print(f"sembrados {N_SLICES} cortes CT sintéticos (serie {series_uid[-12:]}) en {ORTHANC}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
