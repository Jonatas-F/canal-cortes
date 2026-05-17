"""Decide layout do short: PREENCHER (crop 9:16) ou AJUSTAR (letterbox).

Heurística baseada em detecção facial (OpenCV Haar Cascade):
- Amostra 5 frames ao longo do corte
- Conta rostos em cada frame e suas posições horizontais
- Regras:
  * Se em maioria dos frames há 1 rosto centralizado (centro 60%) → PREENCHER
  * Se em algum frame há ≥2 rostos OU rosto fora do centro → AJUSTAR
  * Sem rostos detectados → PREENCHER (assume tela cheia / cena)

Retorna dict: {"layout": "preencher"|"ajustar", "face_counts": [...], "motivo": "..."}
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2

# Cascade vem com opencv-python
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


def extract_frames(video: Path, start: float, end: float, n_samples: int = 5) -> list[Path]:
    """Extrai n_samples frames distribuídos no intervalo."""
    duration = end - start
    timestamps = [start + duration * (i + 1) / (n_samples + 1) for i in range(n_samples)]
    tmpdir = Path(tempfile.mkdtemp(prefix="layout_"))
    paths = []
    for i, ts in enumerate(timestamps):
        out = tmpdir / f"frame_{i:02d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{ts}", "-i", str(video),
             "-frames:v", "1", "-q:v", "3", str(out)],
            check=True, capture_output=True,
        )
        if out.exists():
            paths.append(out)
    return paths


def analyze_frame(path: Path) -> tuple[int, list[tuple[int, int, int, int]], tuple[int, int]]:
    """Retorna (n_faces, list[(x,y,w,h)], (img_w, img_h))."""
    img = cv2.imread(str(path))
    if img is None:
        return 0, [], (0, 0)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    return len(faces), [tuple(f) for f in faces], (w, h)


def decide_layout(video: Path, start: float, end: float) -> dict:
    frames = extract_frames(video, start, end, n_samples=5)
    counts = []
    multi_face_frames = 0
    off_center_frames = 0
    total_frames = 0

    for fp in frames:
        n, faces, (w, h) = analyze_frame(fp)
        counts.append(n)
        total_frames += 1
        if n >= 2:
            multi_face_frames += 1
        elif n == 1 and w > 0:
            fx, fy, fw, fh = faces[0]
            face_center_x = fx + fw / 2
            # Rosto fora do centro 60%? (i.e., centro < 20% ou > 80%)
            rel = face_center_x / w
            if rel < 0.20 or rel > 0.80:
                off_center_frames += 1

    # Cleanup
    for fp in frames:
        try:
            fp.unlink()
            fp.parent.rmdir()
        except OSError:
            pass

    if total_frames == 0:
        return {"layout": "preencher", "motivo": "frames não puderam ser extraídos", "face_counts": []}

    if multi_face_frames >= 2:
        return {
            "layout": "ajustar",
            "motivo": f"{multi_face_frames}/{total_frames} frames com ≥2 rostos",
            "face_counts": counts,
        }
    if off_center_frames >= 3:
        return {
            "layout": "ajustar",
            "motivo": f"{off_center_frames}/{total_frames} frames com rosto fora do centro",
            "face_counts": counts,
        }
    return {
        "layout": "preencher",
        "motivo": "rosto único centralizado (ou sem rostos)",
        "face_counts": counts,
    }


def main() -> None:
    if len(sys.argv) < 4:
        print("uso: layout_analyzer.py <video> <start> <end>")
        sys.exit(1)
    video = Path(sys.argv[1])
    start = float(sys.argv[2])
    end = float(sys.argv[3])
    result = decide_layout(video, start, end)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
