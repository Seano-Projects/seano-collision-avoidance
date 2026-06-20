# SEANO Collision Avoidance System — Analisis & Catatan Pengembangan

> Platform: Jetson Orin | ROS2 Humble | YOLOv8 | ArduRover / ArduPilot (MAVLink/MAVROS)

---

## Daftar Isi

1. [Gambaran Umum Sistem](#1-gambaran-umum-sistem)
2. [Arsitektur Pipeline](#2-arsitektur-pipeline)
3. [Penjelasan Setiap Node](#3-penjelasan-setiap-node)
4. [Alur Deteksi hingga Penghindaran](#4-alur-deteksi-hingga-penghindaran)
5. [Logika Mode Switching AUTO ↔ MANUAL](#5-logika-mode-switching-auto--manual)
6. [Logika RC Override & Kemudi](#6-logika-rc-override--kemudi)
7. [Masalah yang Ditemukan: Perilaku Belum Optimal](#7-masalah-yang-ditemukan-perilaku-belum-optimal)
8. [Masalah CUDA Out of Memory](#8-masalah-cuda-out-of-memory)
9. [Ringkasan Prioritas Perbaikan](#9-ringkasan-prioritas-perbaikan)

---

## 1. Gambaran Umum Sistem

Program ini adalah sistem **collision avoidance (penghindaran tabrakan)** untuk USV (Unmanned Surface Vehicle) berbasis ROS2. Cara kerjanya:

- Kamera menangkap frame secara real-time
- Model YOLOv8 mendeteksi objek di depan kendaraan
- Sistem menghitung **risk score** berdasarkan posisi, ukuran, dan pergerakan objek
- Jika risk cukup tinggi, sistem **ambil alih kendali** dari autopilot: pindah ke mode MANUAL dan kirim sinyal kemudi via `/mavros/rc/override`
- Setelah jalan bersih, sistem kembali ke mode AUTO mengikuti misi asal

Hardware target: **Jetson Orin** (8 GB unified memory, GPU dan CPU berbagi pool memori yang sama).

---

## 2. Arsitektur Pipeline

```
Kamera
  │
  ▼
[detector_node]
  YOLOv8 inference, hanya proses frame terbaru (anti-delay)
  → /camera/detections
  │
  ▼
[false_positive_guard_node]
  Filter temporal N-of-M (mis. 3 hit dalam 8 frame)
  → /camera/detections_filtered
  │
  ▼
[risk_evaluator_node]  ← INTI LOGIKA PENGHINDARAN
  Tracking per-objek, hitung risk score, pilih perintah manuver
  → /ca/risk, /ca/command, /ca/avoid_active, /ca/mode
  │
  ▼
[watchdog_failsafe_node]
  Monitor kesehatan semua sinyal upstream, latch perintah STOP/TURN
  → /ca/command_safe, /ca/failsafe_active
  │
  ▼
[mission_mode_manager_node]
  State machine level tinggi: MISSION ↔ AVOID ↔ REJOIN ↔ FAILSAFE
  Request mode change ke FCU via /mavros/set_mode
  → /ca/mode_manager_state, /seano/operator_manual_authority
  │
  ▼
[mavros_rc_override_bridge_node]
  Terjemahkan perintah throttle/rudder → sinyal PWM
  → /mavros/rc/override
  │
  ▼
FCU (ArduRover/ArduPilot)
  │
  ▼
Aktuator kendaraan
```

### Node Pendukung

| Node | Fungsi |
|------|--------|
| `phase7_mode_authority_bridge.py` | Terjemahkan `/mavros/state` → `/seano/auto_enable` |
| `command_mux_node.py` | Pilih sumber perintah: MANUAL atau AUTO |
| `vision_quality_node.py` | Skor kualitas gambar (blur, gelap, dsb) |
| `frame_freeze_detector_node.py` | Deteksi kamera beku/hang |
| `waterline_horizon_node.py` | Deteksi garis air untuk maritime |
| `multi_target_fusion_node.py` | Fusi multi-objek (opsional) |

---

## 3. Penjelasan Setiap Node

### `detector_node.py`
- **Input:** `/camera/image_raw_reliable`
- **Output:** `/camera/detections`
- Jalankan YOLOv8 hanya pada frame terbaru (backlog di-drop)
- Parameter bisa diubah saat runtime: `conf`, `iou`, `imgsz`, `class_ids`, `max_fps`
- Default: `imgsz=416`, `max_fps=8.0`, `half=false`, `publish_annotated=true`

### `false_positive_guard_node.py`
- **Input:** `/camera/detections`
- **Output:** `/camera/detections_filtered`
- Filter dengan pencocokan IoU antar frame
- Butuh N hit dalam M frame (contoh: 3/8) agar deteksi dianggap valid

### `risk_evaluator_node.py`
- **Input:** `/camera/detections_filtered`
- **Output:** `/ca/risk`, `/ca/command`, `/ca/avoid_active`, `/ca/mode`
- **Kalkulasi risk per objek:**
  - **Proximity:** Seberapa besar bounding box relatif layar
  - **Centrality:** Seberapa dekat ke tengah frame (jalur tabrakan langsung)
  - **Approach:** Laju pertumbuhan area (apakah objek mendekat?)
  - **Bearing Rate:** Seberapa cepat sudut bearing berubah
  - **vTTC:** Estimasi waktu sampai objek mencapai area kritis
  - **VQ Scaling:** Kualitas visual buruk menaikkan safety floor risk
- Risk di-smooth dengan EMA, diambil nilai tertinggi dari semua track

**Tabel risk band (dari config `alfin7_hardware_light.yaml`):**

| Risk | Threshold | Perintah |
|------|-----------|---------|
| Low | < 0.35 | `HOLD_COURSE` |
| Medium | 0.35–0.45 | `SLOW_DOWN`, `TURN_*_SLOW` |
| High | 0.45–0.78 | `TURN_LEFT`, `TURN_RIGHT` |
| Emergency | ≥ 0.78 | `STOP` |

### `watchdog_failsafe_node.py`
- **Input:** `/ca/risk`, `/ca/command`, `/ca/mode`, health signals
- **Output:** `/ca/command_safe`, `/ca/failsafe_active`
- Monitor usia data (image stale, risk stale)
- Terapkan **command dwell** (default 2.0 detik): STOP/TURN di-latch setelah risk turun
- Paksa STOP jika ada timeout yang terlewat

### `mission_mode_manager_node.py`
- **Input:** `/ca/failsafe_active`, `/seano/rc_override_enable`, `/ca/avoid_active`, `/mavros/state`
- **Output:** `/ca/mode_manager_state`, `/seano/operator_manual_authority`
- **State machine:**
  - `MISSION` → Normal, autopilot jalan
  - `AVOID` → rc_override_enable=true, minta FCU ke MANUAL
  - `REJOIN` → Transisi kembali ke AUTO setelah avoid selesai
  - `FAILSAFE` → failsafe_active=true, paksa ke mode aman

### `mavros_rc_override_bridge_node.py`
- **Input:** `/seano/throttle_cmd`, `/seano/rudder_cmd` (atau `left/right_cmd`)
- **Output:** `/mavros/rc/override` (PWM)
- Blokir output jika `rc_override_enable=false` (kirim CHAN_RELEASE)
- Blokir output jika `operator_manual_authority=true` (pilot veto)
- Dukung slew-rate limiting (ramp PWM bertahap)

---

## 4. Alur Deteksi hingga Penghindaran

### Kondisi Normal (AUTO Mission)
1. FCU mode `AUTO` → `phase7_mode_authority_bridge` publish `/seano/auto_enable=true`
2. Tidak ada objek → `risk=0.0`, `command=HOLD_COURSE`
3. `mode_manager_state=MISSION`

### Objek Terdeteksi
1. Detector → `/camera/detections` → false positive guard → `/camera/detections_filtered`
2. Risk evaluator hitung risk ≥ 0.45 → `command=TURN_LEFT`, `avoid_active=true`
3. Watchdog pass-through → `command_safe=TURN_LEFT`

### Pengambilalihan Kemudi
1. `/seano/rc_override_enable=true`
2. Mode manager deteksi → state jadi `AVOID`
3. Mode manager request `/mavros/set_mode = MANUAL`
4. RC override bridge mulai kirim PWM ke CH1 (kemudi) dan CH3 (throttle)

### Jalan Bersih, Kembali ke AUTO
1. Risk turun < 0.28 → `avoid_active=false`
2. Dwell watchdog habis (2 detik)
3. `rc_override_enable=false` → bridge kirim CHAN_RELEASE
4. Mode manager → state `REJOIN`
5. Setelah `rejoin_stable_time_s` (default 2 detik) → state `MISSION`
6. Kendaraan kembali ikut misi AUTO

---

## 5. Logika Mode Switching AUTO ↔ MANUAL

### Masalah yang Ditemukan

#### A. Rantai Signal Terlalu Panjang
Untuk switch AUTO → MANUAL, harus melewati **6 hop** dengan timer dan timeout masing-masing:
```
risk_evaluator → watchdog → mode_manager → FCU → phase7_bridge → rc_bridge
```
Jika salah satu lambat atau message drop, mode switch bisa telat atau gagal sama sekali.

#### B. Threshold Tidak Sinkron Antar Node
- `risk_evaluator` punya `avoid_active_enter_risk` dan `exit_risk` sendiri
- `watchdog_failsafe` punya `avoid_command_risk_threshold` dan `release_risk` sendiri
- Keduanya **tidak saling share state** — bisa race condition di mana `avoid_active=true` tapi watchdog belum latch, atau sebaliknya

#### C. `operator_manual_authority` Guard Tidak Cek Intent Pilot
Guard ini hanya cek apakah FCU sudah di MANUAL (dari `/mavros/state`), bukan apakah pilot sedang aktif pegang stick. Bisa terjadi:
- Pilot switch ke MANUAL → FCU mode belum berubah (lag) → sistem masih kirim override
- Pilot switch ke MANUAL saat obstacle hampir lewat → sistem fight-back ke AUTO terlalu cepat

#### D. Rejoin State Bisa Dilewati
`REJOIN` hanya aktif jika `confirmed_avoid_session=true` DAN durasi ≥ `rejoin_required_avoid_s` (0.5 detik). Kalau sesi avoid terlalu pendek atau `confirmed_avoid_session` belum sempat di-set, kendaraan bisa nyangkut di AVOID/MANUAL tanpa kembali ke AUTO.

---

## 6. Logika RC Override & Kemudi

### Cara Kerja
- Saat `rc_override_enable=true`: bridge kirim nilai PWM ke `/mavros/rc/override`
- Saat `rc_override_enable=false`: bridge kirim `CHAN_RELEASE (0)` → FCU abaikan override
- Saat `operator_manual_authority=true`: output diblokir (pilot veto)

### Masalah yang Ditemukan

#### A. Tidak Ada Spatial Memory Arah Hindaran
Keputusan belok hanya berdasarkan bearing dan bearing rate **frame saat ini**. Tidak ada state yang menyimpan:
- "Objek datang dari sisi kanan"
- "Belum benar-benar bersih, jangan balik dulu"

Akibatnya:
- Sistem tidak tahu dari sisi mana harus balik setelah obstacle hilang
- Kalau bearing rate flip sebentar, sistem bisa belok ke arah obstacle

#### B. `prefer_starboard` Bersifat Global
Tidak ada per-situation override berdasarkan dari mana objek datang. Satu parameter global untuk semua skenario pendekatan.

---

## 7. Masalah yang Ditemukan: Perilaku Belum Optimal

### Ringkasan Semua Isu

| # | Masalah | Dampak Nyata | Node Terkait |
|---|---------|--------------|--------------|
| 1 | Threshold tidak sinkron antara `risk_evaluator` dan `watchdog` | Mode switch gagal / avoidance jitter | `risk_evaluator`, `watchdog_failsafe` |
| 2 | Rantai signal 6-hop untuk mode switch | Latency tinggi, bisa gagal kalau salah satu timeout | Semua node |
| 3 | Tidak ada spatial memory arah hindaran | Belum bersih tapi sudah balik, atau belok ke arah salah | `risk_evaluator` |
| 4 | Rejoin logic fragile | Nyangkut di AVOID/MANUAL | `mission_mode_manager` |
| 5 | `operator_manual_authority` tidak track intent pilot | Bisa fight dengan pilot | `mission_mode_manager` |
| 6 | VQ risk floor terlalu tinggi (0.80) | False positive di kondisi gelap/buram tetap trigger avoidance | `risk_evaluator` |
| 7 | CAUTION mode deescalation lemah | Perilaku jitter di visibilitas marginal | `risk_evaluator` |
| 8 | Tidak ada rate limiting request mode change | Bisa flood FCU dengan request berulang | `mission_mode_manager` |

### Detail Isu Paling Kritis

#### Isu 1 — Threshold Race (Root Cause Utama "Mode Ga Ganti")
```
risk_evaluator: enter_avoid_risk = 0.45, exit_avoid_risk = 0.28
watchdog:       avoid_command_risk_threshold = 0.30, release_risk = 0.25
```
Keduanya tidak sinkron. Bisa terjadi: `avoid_active=true` dari risk_evaluator, tapi watchdog masih belum latch karena threshold-nya beda. Mode manager tidak dapat signal cukup kuat untuk switch.

#### Isu 3 — Tidak Ada Spatial Memory (Root Cause "Masih Belok Padahal Mau Balik")
Tidak ada state yang ingat: "objek terakhir ada di sisi kiri, belum konfirmasi clear, pertahankan hindaran ke kanan." Sistem hanya lihat bearing frame sekarang — kalau objek tiba-tiba hilang dari frame (keluar FOV), sistem langsung anggap bersih.

#### Isu 4 — Rejoin Bisa Dilewati (Root Cause "Tidak Balik ke AUTO")
```python
if confirmed_avoid_session and avoid_duration >= rejoin_required_avoid_s:
    # masuk REJOIN
```
Kalau avoid sangat singkat atau `confirmed_avoid_session` belum di-set tepat waktu, blok ini tidak pernah dieksekusi. Tidak ada fallback timeout yang paksa kembali ke AUTO.

---

## 8. Masalah CUDA Out of Memory

### Konteks Hardware

Jetson Orin menggunakan **Unified Memory Architecture**: GPU dan CPU **berbagi pool fisik yang sama** (8 GB total). Tidak ada VRAM terpisah. Artinya tekanan memori dari semua proses (ROS2 nodes, DDS, kamera) langsung berdampak ke alokasi CUDA.

### Penyebab yang Ditemukan

#### Penyebab 1 — `annotated.copy()` Dipanggil Per Bounding Box (Paling Kritis)

Di `detector_node.py` baris 517:

```python
for (x1, y1, ...) in zip(xyxy, cls, confs):
    if self.draw_label_bg:
        overlay = annotated.copy()          # FULL FRAME COPY tiap box!
        cv2.rectangle(overlay, ...)
        annotated[:] = cv2.addWeighted(overlay, ...)
```

Jika ada 10 objek terdeteksi → **10 salinan penuh frame 640×480** dibuat dalam satu loop.
Di Orin: 10 × 640×480×3 byte = ~9 MB alokasi per inference tick, pada pool yang sama dengan CUDA.

**Cara benar:** `overlay = annotated.copy()` seharusnya di luar loop, bukan di dalam.

#### Penyebab 2 — Tidak Ada `torch.cuda.empty_cache()`

PyTorch tidak langsung melepas memori CUDA ke OS setelah inference — dia cache untuk reuse. Setelah berjam-jam running tanpa restart, cache ini terfragmentasi dan mengembang. Tidak ada satupun panggilan `torch.cuda.empty_cache()` di codebase. Lama kelamaan alokasi baru gagal meski "seharusnya" ada ruang.

#### Penyebab 3 — `half=False` (FP32) di Hardware yang Dirancang untuk FP16

```yaml
ca_det_half: false  # default di launch file
```

Jetson Orin punya Tensor Core yang optimal untuk FP16. Dengan FP32, pemakaian VRAM selama inference **2× lebih besar** dari yang dibutuhkan. Parameter ini sudah tersedia, tinggal diaktifkan.

#### Penyebab 4 — `result` Object Tidak Di-release Secara Eksplisit

```python
result = self.model.predict(source=frame, ...)[0]
# ... dipakai ambil xyxy, cls, conf ...
# tidak ada del result
```

Object `result` dari Ultralytics bisa menahan CUDA tensors internal. Tanpa `del result`, Python GC yang menentukan kapan dibersihkan — tidak deterministik. Di loop 8 FPS, GC bisa tidak sempat jalan sebelum inference berikutnya.

#### Penyebab 5 — `publish_annotated=True` Default

```yaml
ca_det_publish_annotated: true  # default
```

8 FPS × 640×480×3 byte = **~7.4 MB/s** alokasi terus-menerus untuk annotated frame, ditambah salinan lagi oleh DDS transport ROS2. Bukan penyebab langsung OOM tapi menambah tekanan ke pool memori yang sama.

#### Penyebab 6 — `device=""` (Auto-select) Tidak Stabil

```yaml
ca_det_device: ""  # kosong = auto
```

Saat device kosong, Ultralytics auto-select device setiap panggilan. Dalam kondisi memory pressure, bisa terjadi re-allocation atau transfer tensor antar device yang menyebabkan spike memori sementara.

### Tabel Ringkasan CUDA OOM

| # | Penyebab | Lokasi | Dampak |
|---|---------|--------|--------|
| 1 | `annotated.copy()` per bounding box dalam loop | `detector_node.py:517` | Spike ~9MB per tick saat banyak deteksi |
| 2 | Tidak ada `torch.cuda.empty_cache()` | Seluruh file | Fragmentasi memori kumulatif → OOM lama-lama |
| 3 | `half=False` (FP32) | Launch file | 2× VRAM vs FP16 |
| 4 | `result` tidak di-`del` | `detector_node.py:427` | GC tidak deterministik |
| 5 | `publish_annotated=True` default | Launch file | +7.4 MB/s alokasi CPU (pool sama) |
| 6 | `device=""` (auto) | Launch file | Potential tensor re-allocation |

---

## 9. Ringkasan Prioritas Perbaikan

### Prioritas Tinggi (langsung ke gejala utama)

| Prioritas | Masalah | Saran Perbaikan |
|-----------|---------|-----------------|
| P1 | `annotated.copy()` dalam loop per-box | Pindahkan ke luar loop, buat satu copy saja |
| P1 | Threshold tidak sinkron antar node | Selaraskan `enter/exit_avoid_risk` di kedua node |
| P2 | Tidak ada `torch.cuda.empty_cache()` | Tambahkan periodik (tiap N frame atau tiap detik) |
| P2 | Rejoin bisa dilewati | Tambahkan timeout fallback paksa kembali ke AUTO |
| P2 | `half=False` di Jetson Orin | Set `ca_det_half=true` di launch file |

### Prioritas Sedang

| Prioritas | Masalah | Saran Perbaikan |
|-----------|---------|-----------------|
| P3 | Tidak ada spatial memory arah hindaran | Tambahkan state "sisi hindaran aktif" + minimum clear time |
| P3 | `device=""` (auto) | Set eksplisit `device=cuda:0` |
| P3 | `publish_annotated=True` saat produksi | Nonaktifkan jika tidak ada monitoring visual |
| P4 | `operator_manual_authority` tidak cek intent | Tambahkan deteksi stick input / dwell sebelum veto |
| P4 | VQ risk floor 0.80 terlalu tinggi | Turunkan atau buat adaptif saat freeze terdeteksi |

---

*Dokumen ini dihasilkan dari analisis kode pada Juni 2026. File utama yang dianalisis: `detector_node.py`, `risk_evaluator_node.py`, `watchdog_failsafe_node.py`, `mission_mode_manager_node.py`, `mavros_rc_override_bridge_node.py`, `phase7_mode_authority_bridge.py`.*
