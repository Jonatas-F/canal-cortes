"""Gera capas automáticas estilo template HTML/CSS + Playwright.

Pipeline:
1. Extrai N frames do source com rostos detectados (OpenCV)
2. Crop por rosto, com padding pra incluir ombros
3. Remove fundo com rembg (modelo isnet-general-use)
4. Renderiza assets/cover_template/template.html via Jinja2 com:
   - logo 14 Garras
   - imagens dos rostos
   - título do corte (com palavra-chave destacada em laranja)
5. Playwright abre o HTML, screenshot 1280x720 JPG

Resultado: cuts/<source>/thumbnails/<cut>_cover.jpg
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
from pathlib import Path

import cv2

from common import ROOT

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
EYE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_eye.xml"
TEMPLATE_DIR = ROOT / "assets" / "cover_template"
LOGO_PATH = TEMPLATE_DIR / "logo_14garras.png"


def _to_data_uri(image_bytes: bytes, mime: str = "image/png") -> str:
    """Embed imagem no HTML como data URI (evita problemas de file:// no Playwright)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _file_to_data_uri(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
    return _to_data_uri(path.read_bytes(), mime)


def _is_likely_face(crop_h: int, crop_w: int) -> bool:
    """Aspect ratio típico de rosto (com ombros)."""
    if crop_w == 0:
        return False
    ratio = crop_h / crop_w
    return 0.7 <= ratio <= 1.6


def _nms_faces(faces: list, overlap_threshold: float = 0.3) -> list:
    """Non-Max Suppression: remove bboxes sobrepostos, mantendo o maior."""
    if not faces:
        return []
    # Ordena por área (maior primeiro)
    sorted_faces = sorted(faces, key=lambda f: -f[2] * f[3])
    kept = []
    for f in sorted_faces:
        x1, y1, w1, h1 = f
        overlap = False
        for k in kept:
            x2, y2, w2, h2 = k
            # IoU simplificado
            ix1 = max(x1, x2); iy1 = max(y1, y2)
            ix2 = min(x1 + w1, x2 + w2); iy2 = min(y1 + h1, y2 + h2)
            iw = max(0, ix2 - ix1); ih = max(0, iy2 - iy1)
            intersection = iw * ih
            min_area = min(w1 * h1, w2 * h2)
            if min_area > 0 and intersection / min_area > overlap_threshold:
                overlap = True
                break
        if not overlap:
            kept.append(f)
    return kept


def _has_eyes(face_roi_gray) -> bool:
    """Verifica se a região tem pelo menos 1 olho detectado.

    Filtra microfones, copos, círculos que parecem rosto pro Haar mas não têm olhos.
    """
    eye_cascade = cv2.CascadeClassifier(EYE_CASCADE_PATH)
    eyes = eye_cascade.detectMultiScale(face_roi_gray, scaleFactor=1.1, minNeighbors=4, minSize=(15, 15))
    return len(eyes) >= 1


def _has_skin_color(img_bgr) -> bool:
    """Verifica se a região tem pelo menos 8% de pixels com cor de pele.

    Filtra microfones, copos, objetos coloridos que o Haar confunde com rosto.
    Cor de pele: HSV H 0-25 ou H 160-180, S 30-180, V 60-255.
    """
    import numpy as np
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # Range 1: tons quentes (H 0-25)
    lower1 = np.array([0, 30, 60])
    upper1 = np.array([25, 180, 255])
    mask1 = cv2.inRange(hsv, lower1, upper1)
    # Range 2: tons rosados (H 160-180, wrap-around)
    lower2 = np.array([160, 30, 60])
    upper2 = np.array([180, 180, 255])
    mask2 = cv2.inRange(hsv, lower2, upper2)
    skin_mask = cv2.bitwise_or(mask1, mask2)
    skin_ratio = float(skin_mask.sum()) / (255.0 * skin_mask.size)
    return skin_ratio > 0.08


def _detect_faces_in_video(
    video: Path,
    timestamps: list[float],
    require_exact_n: int | None = None,
) -> list[tuple[int, bytes, float, float]]:
    """Helper LEGACY: agora prefira _find_best_grid_frame que retorna rostos
    do MESMO frame (garante pessoas distintas)."""
    import subprocess
    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    tmpdir = Path(tempfile.mkdtemp(prefix="cf_"))
    candidates: list[tuple[int, bytes, float, float]] = []
    for i, ts in enumerate(timestamps):
        frame_path = tmpdir / f"f{i:03d}.png"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ts}", "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", str(frame_path)],
                check=True, capture_output=True,
            )
        except Exception:
            continue
        img = cv2.imread(str(frame_path))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if require_exact_n is not None and len(faces) != require_exact_n:
            continue
        if require_exact_n is None and len(faces) < 2:
            continue
        ih, iw = img.shape[:2]
        for (x, y, w, h) in faces:
            pad_x = int(w * 0.4); pad_y_top = int(h * 0.4); pad_y_bot = int(h * 1.2)
            cx1 = max(0, x - pad_x); cy1 = max(0, y - pad_y_top)
            cx2 = min(iw, x + w + pad_x); cy2 = min(ih, y + h + pad_y_bot)
            crop = img[cy1:cy2, cx1:cx2]
            if crop.size == 0 or not _is_likely_face(crop.shape[0], crop.shape[1]):
                continue
            ok, buf = cv2.imencode(".png", crop)
            if ok:
                candidates.append((w*h, buf.tobytes(), (x+w/2)/iw, (y+h/2)/ih))
    for f in tmpdir.glob("*.png"):
        try: f.unlink()
        except OSError: pass
    try: tmpdir.rmdir()
    except OSError: pass
    return candidates


def _find_best_grid_frame(
    video: Path,
    timestamps: list[float],
    target_n: int,
) -> list[bytes] | None:
    """Acha o frame com EXATAMENTE target_n rostos melhor distribuídos horizontalmente.

    Retorna lista de PNG bytes (ordenados esquerda → direita) ou None se não achar.
    Vantagem vs clustering: pega N pessoas DIFERENTES do mesmo frame.
    """
    import subprocess
    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    tmpdir = Path(tempfile.mkdtemp(prefix="grid_"))

    best_frame = None  # (spread_score, faces_list)
    for i, ts in enumerate(timestamps):
        frame_path = tmpdir / f"f{i:03d}.png"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ts}", "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", str(frame_path)],
                check=True, capture_output=True,
            )
        except Exception:
            continue
        img = cv2.imread(str(frame_path))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Permitir mais detecções e pós-filtrar
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        # NMS: remove sobreposições (mesma pessoa detectada 2x próximo)
        faces = _nms_faces(list(faces), overlap_threshold=0.3)
        if len(faces) < target_n:
            continue
        ih, iw = img.shape[:2]
        valid_faces = []
        for (x, y, w, h) in faces:
            if not _is_likely_face(h, w):
                continue
            face_roi = img[y:y+h, x:x+w]
            if face_roi.size == 0:
                continue
            if not _has_skin_color(face_roi):
                continue
            face_roi_gray = gray[y:y+h, x:x+w]
            if not _has_eyes(face_roi_gray):
                continue
            valid_faces.append((x, y, w, h))
        # Após filtro, precisa de exatamente target_n. Se sobrou mais, pega os maiores.
        if len(valid_faces) < target_n:
            continue
        if len(valid_faces) > target_n:
            valid_faces = sorted(valid_faces, key=lambda f: -f[2] * f[3])[:target_n]
        # Score: maior spread horizontal entre rostos (mais espalhados = melhor)
        xs = sorted([f[0] + f[2] / 2 for f in valid_faces])
        spread = (xs[-1] - xs[0]) / iw
        # Bônus: rostos não devem se sobrepor
        valid_faces_sorted = sorted(valid_faces, key=lambda f: f[0])
        # Recorta cada um com padding
        crops_png = []
        ok_frame = True
        for (x, y, w, h) in valid_faces_sorted:
            pad_x = int(w * 0.4); pad_y_top = int(h * 0.4); pad_y_bot = int(h * 1.3)
            cx1 = max(0, x - pad_x); cy1 = max(0, y - pad_y_top)
            cx2 = min(iw, x + w + pad_x); cy2 = min(ih, y + h + pad_y_bot)
            crop = img[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                ok_frame = False
                break
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                ok_frame = False
                break
            crops_png.append(buf.tobytes())
        if not ok_frame:
            continue
        if best_frame is None or spread > best_frame[0]:
            best_frame = (spread, crops_png)

    for f in tmpdir.glob("*.png"):
        try: f.unlink()
        except OSError: pass
    try: tmpdir.rmdir()
    except OSError: pass

    return best_frame[1] if best_frame else None


def _sharpness_score(crop_bgr) -> float:
    """Variance of Laplacian — higher = sharper image (less blur)."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _face_quality_score(crop_bgr, face_w: int, face_h: int) -> float:
    """Score combinado: sharpness + tamanho + olhos detectados."""
    sharpness = _sharpness_score(crop_bgr)
    size_score = (face_w * face_h) / (200 * 200)  # normaliza ~1.0 pra rosto 200x200
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    eye_cascade = cv2.CascadeClassifier(EYE_CASCADE_PATH)
    eyes = eye_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(15, 15))
    eye_bonus = 1.5 if len(eyes) >= 2 else (1.2 if len(eyes) == 1 else 0.8)
    # Score final: sharpness x tamanho x bônus de olhos
    return sharpness * (1.0 + size_score * 0.5) * eye_bonus


def detect_hosts_in_intro(
    video: Path,
    cut_start: float,
    cut_end: float,
    intro_duration: float = 30.0,
    max_prints: int = 20,
    max_hosts: int = 4,
    min_recurrence_in_intro: int = 3,
    spatial_radius: float = 0.10,
    source: str = "video",   # "video": primeiros N segundos do source / "cut": do corte
) -> list[bytes]:
    """Detecta hosts amostrando frames dos PRIMEIROS `intro_duration` segundos do VÍDEO FONTE.

    A abertura do podcast (intro) mostra TODOS os hosts no grid principal.
    Por isso amostrar do INÍCIO do source.mp4 é mais confiável que do corte
    (que pode ter close-up solo).

    Estratégia:
    1. Amostra até max_prints frames distribuídos nos primeiros intro_duration segundos
    2. Detecta rostos válidos em cada (com filtros: aspect, skin, eyes, size, NMS)
    3. Filtra frames com muitos rostos (>4 = slide/composite)
    4. Cluster por posição
    5. Mantém clusters com >= min_recurrence_in_intro aparições
    6. Pra cada cluster, escolhe o crop com MELHOR qualidade
    """
    import subprocess
    import tempfile

    if source == "cut":
        # Modo legado: do início do corte
        actual_duration = min(intro_duration, cut_end - cut_start)
        n_samples = min(max_prints, max(5, int(actual_duration)))
        timestamps = [
            cut_start + actual_duration * (i + 1) / (n_samples + 1)
            for i in range(n_samples)
        ]
    else:
        # Modo padrão: primeiros N segundos do source (intro do podcast).
        # Vinheta inicial pode não ter rostos — pula primeiros 10s.
        skip_initial_seconds = 10.0
        n_samples = max_prints
        usable_window = max(20.0, intro_duration - skip_initial_seconds)
        timestamps = [
            skip_initial_seconds + usable_window * (i + 1) / (n_samples + 1)
            for i in range(n_samples)
        ]

    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    tmpdir = Path(tempfile.mkdtemp(prefix="intro_"))

    all_detections: list[tuple[float, float, float, bytes]] = []
    frames_with_faces = 0
    MIN_FACE_RATIO = 0.07   # rosto deve ser >= 7% da largura do frame (filtra slides)
    MAX_FACES_PER_FRAME = 4  # frames com >4 rostos = provável slide/composite

    for i, ts in enumerate(timestamps):
        frame_path = tmpdir / f"f{i:03d}.png"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ts}", "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", str(frame_path)],
                check=True, capture_output=True,
            )
        except Exception:
            continue
        img = cv2.imread(str(frame_path))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        faces = _nms_faces(list(faces), overlap_threshold=0.3)
        ih, iw = img.shape[:2]
        # Filtro 1: skip frames com muitos rostos (= provável slide)
        if len(faces) > MAX_FACES_PER_FRAME:
            continue
        valid_in_frame = 0
        for (x, y, w, h) in faces:
            # Filtro 2: rostos pequenos = composite slide, descarta
            if w / iw < MIN_FACE_RATIO:
                continue
            if not _is_likely_face(h, w):
                continue
            face_roi_color = img[y:y+h, x:x+w]
            if face_roi_color.size == 0 or not _has_skin_color(face_roi_color):
                continue
            face_roi_gray = gray[y:y+h, x:x+w]
            if not _has_eyes(face_roi_gray):
                continue
            pad_x = int(w * 0.4); pad_y_top = int(h * 0.4); pad_y_bot = int(h * 1.3)
            cx1 = max(0, x - pad_x); cy1 = max(0, y - pad_y_top)
            cx2 = min(iw, x + w + pad_x); cy2 = min(ih, y + h + pad_y_bot)
            crop = img[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue
            score = _face_quality_score(face_roi_color, w, h)
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                continue
            rel_x = (x + w / 2) / iw
            rel_y = (y + h / 2) / ih
            all_detections.append((rel_x, rel_y, score, buf.tobytes()))
            valid_in_frame += 1
        if valid_in_frame > 0:
            frames_with_faces += 1

    for f in tmpdir.glob("*.png"):
        try: f.unlink()
        except OSError: pass
    try: tmpdir.rmdir()
    except OSError: pass

    print(f"[cover_html] intro: {n_samples} prints amostrados, {frames_with_faces} c/ rostos, {len(all_detections)} detecções")

    if not all_detections:
        return []

    # Cluster por posição
    clusters: list[list[tuple[float, float, float, bytes]]] = []
    for det in all_detections:
        rel_x, rel_y, score, png = det
        placed = False
        for cluster in clusters:
            cx = sum(d[0] for d in cluster) / len(cluster)
            cy = sum(d[1] for d in cluster) / len(cluster)
            dist = ((rel_x - cx) ** 2 + (rel_y - cy) ** 2) ** 0.5
            if dist < spatial_radius:
                cluster.append(det)
                placed = True
                break
        if not placed:
            clusters.append([det])

    recurring = [c for c in clusters if len(c) >= min_recurrence_in_intro]
    recurring.sort(key=lambda c: -len(c))

    print(f"[cover_html] intro: {len(clusters)} cluster(s) total, {len(recurring)} recorrente(s) "
          f"(threshold {min_recurrence_in_intro}/{n_samples})")
    for i, c in enumerate(recurring[:max_hosts]):
        avg_x = sum(d[0] for d in c) / len(c)
        print(f"[cover_html]   host {i+1}: {len(c)} aparições no intro, x={avg_x:.2f}")

    # Best angle por cluster
    selected: list[tuple[float, bytes]] = []
    for cluster in recurring[:max_hosts]:
        best = max(cluster, key=lambda d: d[2])
        selected.append((best[0], best[3]))
    selected.sort(key=lambda s: s[0])
    return [s[1] for s in selected]


def detect_recurring_hosts(
    video: Path,
    max_hosts: int = 4,
    n_sample_frames: int = 80,
    min_recurrence: float = 0.10,  # rosto deve aparecer em ≥10% dos frames
    spatial_radius: float = 0.10,   # cluster radius em coords normalizadas
) -> list[bytes]:
    """Detecta HOSTS recorrentes do podcast, IGNORANDO b-roll/convidados pontuais.

    Estratégia:
    1. Amostra muitos frames do vídeo inteiro
    2. Detecta TODOS os rostos válidos em cada frame
    3. Cluster por posição (rel_x, rel_y) com raio pequeno
       — hosts ficam sempre no mesmo lugar (câmera fixa do podcast)
       — b-roll aparece em posições/frames esporádicos
    4. Mantém só clusters com frequência >= min_recurrence (= host real)
    5. Pra cada cluster, escolhe o crop com MELHOR QUALIDADE
       (sharpness + tamanho + olhos abertos)
    """
    import subprocess
    import tempfile

    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    total_duration = float(r.stdout.strip())
    timestamps = [total_duration * (i + 1) / (n_sample_frames + 1) for i in range(n_sample_frames)]

    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    tmpdir = Path(tempfile.mkdtemp(prefix="hosts_"))

    # Coleta TODOS os rostos válidos: (rel_x, rel_y, score, crop_png)
    all_detections: list[tuple[float, float, float, bytes]] = []

    for i, ts in enumerate(timestamps):
        frame_path = tmpdir / f"f{i:03d}.png"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ts}", "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", str(frame_path)],
                check=True, capture_output=True,
            )
        except Exception:
            continue
        img = cv2.imread(str(frame_path))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        faces = _nms_faces(list(faces), overlap_threshold=0.3)
        ih, iw = img.shape[:2]
        for (x, y, w, h) in faces:
            if not _is_likely_face(h, w):
                continue
            face_roi_color = img[y:y+h, x:x+w]
            if face_roi_color.size == 0:
                continue
            if not _has_skin_color(face_roi_color):
                continue
            face_roi_gray = gray[y:y+h, x:x+w]
            if not _has_eyes(face_roi_gray):
                continue
            # Crop com padding pra incluir ombros (pro cutout)
            pad_x = int(w * 0.4); pad_y_top = int(h * 0.4); pad_y_bot = int(h * 1.3)
            cx1 = max(0, x - pad_x); cy1 = max(0, y - pad_y_top)
            cx2 = min(iw, x + w + pad_x); cy2 = min(ih, y + h + pad_y_bot)
            crop = img[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue
            score = _face_quality_score(face_roi_color, w, h)
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                continue
            rel_x = (x + w / 2) / iw
            rel_y = (y + h / 2) / ih
            all_detections.append((rel_x, rel_y, score, buf.tobytes()))

    for f in tmpdir.glob("*.png"):
        try: f.unlink()
        except OSError: pass
    try: tmpdir.rmdir()
    except OSError: pass

    if not all_detections:
        print("[cover_html] nenhum rosto válido detectado")
        return []

    # Cluster por posição: agrupa detecções dentro do raio
    clusters: list[list[tuple[float, float, float, bytes]]] = []
    for det in all_detections:
        rel_x, rel_y, score, png = det
        placed = False
        for cluster in clusters:
            # Centro do cluster (média)
            cx = sum(d[0] for d in cluster) / len(cluster)
            cy = sum(d[1] for d in cluster) / len(cluster)
            dist = ((rel_x - cx) ** 2 + (rel_y - cy) ** 2) ** 0.5
            if dist < spatial_radius:
                cluster.append(det)
                placed = True
                break
        if not placed:
            clusters.append([det])

    # Filtra clusters por recorrência (host = aparece em ≥ min_recurrence dos frames)
    min_occurrences = max(2, int(n_sample_frames * min_recurrence))
    recurring = [c for c in clusters if len(c) >= min_occurrences]
    recurring.sort(key=lambda c: -len(c))  # mais frequentes primeiro

    print(f"[cover_html] {len(clusters)} cluster(s) total, {len(recurring)} recorrente(s) "
          f"(threshold {min_occurrences}/{n_sample_frames})")
    for i, c in enumerate(recurring[:max_hosts]):
        avg_x = sum(d[0] for d in c) / len(c)
        print(f"[cover_html]   host {i+1}: {len(c)} aparições, x={avg_x:.2f}")

    # Pra cada cluster recorrente, pega o crop com MAIOR score de qualidade
    selected: list[tuple[float, bytes]] = []
    for cluster in recurring[:max_hosts]:
        best = max(cluster, key=lambda d: d[2])  # maior score
        selected.append((best[0], best[3]))  # (rel_x, png)

    # Ordena da esquerda pra direita
    selected.sort(key=lambda s: s[0])
    return [s[1] for s in selected]


def detect_all_participants(
    video: Path,
    max_faces: int = 6,
    min_faces: int = 2,
    n_sample_frames: int = 60,
) -> list[bytes]:
    """Auto-detecta o número de PARTICIPANTES (hosts + convidados) no vídeo.

    Estratégia:
    1. Amostra N frames do vídeo INTEIRO
    2. Conta quantos rostos válidos aparecem em cada frame
    3. O número MÁS frequente de rostos = número de participantes do grid
    4. Retorna crops da MELHOR frame com esse N (rostos bem espalhados)
    """
    import subprocess
    from collections import Counter

    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    total_duration = float(r.stdout.strip())
    timestamps = [total_duration * (i + 1) / (n_sample_frames + 1) for i in range(n_sample_frames)]

    # Tenta vários N (do maior pro menor) e devolve o primeiro frame com N rostos válidos
    for target_n in range(max_faces, min_faces - 1, -1):
        crops = _find_best_grid_frame(video, timestamps, target_n)
        if crops:
            print(f"[cover_html] detectados {target_n} participantes (grid completo achado)")
            return crops
    print(f"[cover_html] fallback: nenhum grid com {min_faces}-{max_faces} rostos achado")
    return []


def extract_speaker_faces(
    video: Path,
    start: float,
    end: float,
    n_faces: int = 3,
    n_sample_frames: int = 40,
) -> list[bytes]:
    """Procura rostos dos PODCAST HOSTS, evitando b-roll.

    Nova estratégia (single-frame): acha um frame único que tenha N rostos
    bem distribuídos horizontalmente — garante N PESSOAS DIFERENTES.

    Fallback: clustering de múltiplos frames (pode duplicar pessoas).
    """
    duration = end - start
    timestamps_cut = [start + duration * (i + 1) / (n_sample_frames + 1) for i in range(n_sample_frames)]

    # Estratégia preferida: frame único com N rostos bem espalhados
    best = _find_best_grid_frame(video, timestamps_cut, n_faces)
    if best:
        print(f"[cover_html] frame único com {n_faces} rostos achado no corte ✅")
        return best

    # Tenta no vídeo inteiro
    import subprocess
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    total_duration = float(r.stdout.strip())
    full_timestamps = [total_duration * (i + 1) / 101 for i in range(100)]
    best = _find_best_grid_frame(video, full_timestamps, n_faces)
    if best:
        print(f"[cover_html] frame único com {n_faces} rostos achado no vídeo inteiro ✅")
        return best

    # Tenta com N-1 rostos (talvez só 2 hosts apareçam)
    if n_faces > 2:
        best = _find_best_grid_frame(video, full_timestamps, n_faces - 1)
        if best:
            print(f"[cover_html] frame com {n_faces - 1} rostos (fallback)")
            return best

    # Último recurso: clustering multi-frame (pode duplicar)
    candidates = _detect_faces_in_video(video, timestamps_cut, require_exact_n=None)
    if not candidates:
        return []
    POSITION_BUCKETS = n_faces
    buckets: dict[int, list] = {}
    for cand in candidates:
        bucket = min(int(cand[2] * POSITION_BUCKETS), POSITION_BUCKETS - 1)
        buckets.setdefault(bucket, []).append(cand)
    selected = []
    for b in sorted(buckets.keys()):
        biggest = max(buckets[b], key=lambda c: c[0])
        selected.append(biggest[1])
    print(f"[cover_html] fallback clustering ({len(selected)} rostos — pode duplicar)")
    return selected


def remove_background(png_bytes: bytes) -> bytes:
    """Remove fundo com rembg (modelo u2net padrão, ~170MB no primeiro uso)."""
    from rembg import remove
    return remove(png_bytes)


def render_cover(
    video: Path,
    cut_start: float,
    cut_end: float,
    titulo: str,
    out_path: Path,
    n_faces: int = 3,
    use_background_removal: bool = True,
) -> None:
    """Gera capa HTML → screenshot JPG."""
    from jinja2 import Template
    from playwright.sync_api import sync_playwright

    # 1. Extrai rostos
    face_png_list = extract_speaker_faces(video, cut_start, cut_end, n_faces=n_faces)
    if not face_png_list:
        raise RuntimeError("nenhum rosto detectado no corte — não dá pra montar capa HTML")

    # 2. Remove fundo (opcional)
    faces_data = []
    for i, png in enumerate(face_png_list):
        if use_background_removal:
            try:
                png = remove_background(png)
            except Exception as e:
                print(f"[cover_html] aviso: rembg falhou no rosto {i}, usando crop puro ({e})")
        faces_data.append({
            "image_url": _to_data_uri(png, "image/png"),
            "name": "",  # opcional — pode ser preenchido manualmente no manifest
        })

    # 3. Destaca uma palavra no título (a maior ou primeira palavra "forte")
    title_html = _highlight_word(titulo)

    # 4. Renderiza HTML
    template = Template((TEMPLATE_DIR / "template.html").read_text(encoding="utf-8"))
    logo_uri = _file_to_data_uri(LOGO_PATH) if LOGO_PATH.exists() else ""
    html = template.render(
        title_html=title_html,
        faces=faces_data,
        logo_url=logo_uri,
    )

    # 5. Screenshot com Playwright
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(html, wait_until="load")
        # Espera fontes web e imagens carregarem
        page.wait_for_load_state("networkidle", timeout=15000)
        page.screenshot(path=str(out_path), full_page=False, type="jpeg", quality=90,
                        clip={"x": 0, "y": 0, "width": 1280, "height": 720})
        browser.close()


def _highlight_word(titulo: str) -> str:
    """Escolhe 1-2 palavras "fortes" pra envolver em <span class='highlight'>.

    Heurística: a palavra mais longa do título OU palavra em CAIXA-ALTA, OU
    a 2ª palavra (geralmente o verbo/sujeito principal). Resto fica branco.
    """
    words = titulo.split()
    if not words:
        return titulo
    # Procura palavra ALL-CAPS
    for i, w in enumerate(words):
        clean = "".join(c for c in w if c.isalpha())
        if len(clean) >= 4 and clean.isupper():
            words[i] = f'<span class="highlight">{w}</span>'
            return " ".join(words)
    # Palavra mais longa (4+ chars)
    idx_longest = max(range(len(words)), key=lambda j: len(words[j]) if len(words[j]) >= 5 else 0)
    if len(words[idx_longest]) >= 5:
        words[idx_longest] = f'<span class="highlight">{words[idx_longest]}</span>'
    return " ".join(words)


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: cover_html.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]

    import json
    cuts_dir = ROOT / "cuts" / source_id
    raw_dir = ROOT / "raw" / source_id
    source = raw_dir / "source.mp4"
    plan = json.loads((cuts_dir / "plan.json").read_text(encoding="utf-8"))
    thumbs_dir = cuts_dir / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    longs_n = 0
    for cut in plan["cortes"]:
        if cut["tipo"] != "long":
            continue
        longs_n += 1
        out = thumbs_dir / f"long_{longs_n:02d}_cover_html.jpg"
        print(f"[cover_html] long_{longs_n:02d}: {cut['titulo'][:60]}...")
        try:
            render_cover(source, cut["start"], cut["end"], cut["titulo"], out)
            print(f"[cover_html]   ✅ {out.name}")
        except Exception as e:
            print(f"[cover_html]   ❌ {e}")


if __name__ == "__main__":
    main()
