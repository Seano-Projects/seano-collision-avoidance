# REPO_MAP.md — Peta Struktur Repo

Dokumen ini murni referensi/navigasi. Tidak ada kode yang diubah untuk membuat
dokumen ini. Kalau ada perbedaan antara dokumen ini dan kode aktual, **kode
yang benar** — perbarui dokumen ini, jangan sebaliknya.

## 1. Struktur repo (ringkas)

```
seano-collision-avoidance2/
├── AGENTS.md                 # panduan kerja untuk AI assistant di repo ini
├── PRD.md                    # tujuan proyek & requirement sistem
├── SKILLS.md                 # skill khusus yang relevan untuk repo ini
├── README.md                 # pintu masuk dokumentasi, quick start
├── docs/                     # catatan teknis lintas-workspace (lihat §2.5)
└── seano_ca_ws/               # workspace ROS2 (colcon) — lihat §2.4
    ├── run_phase7_monitor_no_log.sh
    ├── run_pool_existing_control_path.sh
    ├── stop_phase7_safe.sh
    ├── phase7_mode_authority_bridge.py
    ├── scripts/               # utilitas non-node (lihat §2.5b)
    ├── docs/                  # catatan teknis khusus workspace
    └── src/seano_vision/       # package ROS2 utama
        ├── seano_vision/       # source node Python (lihat §2.1)
        ├── launch/             # launch file (lihat §2.2)
        ├── config/             # file konfigurasi YAML (lihat §2.3)
        └── models/             # model YOLOv8 (lihat §2.4b)
```

`build/`, `install/`, `log/` (baik di root maupun di dalam `seano_ca_ws/`) tidak
ada dalam peta ini karena itu output `colcon build` — regenerable, gitignored,
lihat [CLEANUP_NOTES.md](CLEANUP_NOTES.md).

---

## 2. Folder penting

### 2.1 `seano_ca_ws/src/seano_vision/seano_vision/` — source node Python

Ini adalah inti sistem: setiap file `*_node.py` di sini adalah satu node ROS2.
Node-node ini dipakai oleh **dua profile runtime** berbeda yang diatur lewat
argumen `ca_runtime_profile` di `phase7_cuav_usb_hardware.launch.py`:

- **`usb_watchdog`** — profile default/aktif sekarang (dipakai
  `run_pool_existing_control_path.sh`). Alurnya:
  ```
  kamera → detector_node → risk_evaluator_node → watchdog_failsafe_node
    → command_mux_node → actuator_safety_limiter_node
    → (mavros_rc_override_bridge_node — TIDAK dijalankan pada skema pool
       existing-control-path, lihat §4)
  ```
  Lihat §4 untuk daftar lengkap node yang aktif pada profile ini.
- **`full`** — profile lengkap opsional yang menambahkan
  `false_positive_guard_node`, `multi_target_fusion_node`,
  `vision_quality_node`, `frame_freeze_detector_node`, dan
  `waterline_horizon_node` ke alur di atas. Lihat §5.

`event_logger_node.py` dan `mission_mode_manager_node.py` mengamati/mengatur
state di sekeliling alur di atas, bukan bagian dari jalur data utama.

> Diagram lengkap arsitektur pipeline (semua node, semua profile) ada di
> `seano_ca_ws/README.md` §2–§3 — dokumen itu menjelaskan pipeline secara
> arsitektural/menyeluruh, sementara §4 dan §5 di dokumen ini menjelaskan node
> mana yang **benar-benar berjalan** pada skema pengujian saat ini.

### 2.2 `seano_ca_ws/src/seano_vision/launch/` — launch file

Berisi definisi `ros2 launch` yang merangkai node-node di atas dengan argumen
yang bisa diatur. `phase7_cuav_usb_hardware.launch.py` adalah baseline aktif
untuk hardware Jetson + kamera USB (lihat §3).

### 2.3 `seano_ca_ws/src/seano_vision/config/` — konfigurasi YAML

Parameter non-default untuk skenario tertentu (mis. kamera RTSP, kamera USB,
baseline hardware ringan). Dipakai sebagai parameter file opsional saat
launch, bukan menggantikan argumen launch.

### 2.4 `seano_ca_ws/src/seano_vision/models/` — model YOLOv8

- `yolov8n.pt` — model sumber (tracked di git).
- `yolov8n.onnx`, `yolov8n.engine` — hasil export/build TensorRT untuk Jetson
  (gitignored karena besar & spesifik-hardware, **tapi aktif dipakai runtime**
  — jangan dihapus, lihat [CLEANUP_NOTES.md](CLEANUP_NOTES.md)).

### 2.4b `seano_ca_ws/` (root workspace)

Berisi script run/stop, bridge helper Python kecil
(`phase7_mode_authority_bridge.py`), dan folder runtime (`.phase7_runtime/`,
penanda `.last_*`) yang dibuat otomatis saat script run dijalankan.

### 2.5 `seano_ca_ws/scripts/` — utilitas non-node

Script Python bantu yang **bukan** node ROS2:
- `phase7_pretty_live.py` — pretty-printer live log untuk `run_phase7_monitor_no_log.sh`.
- `check_phase7_sync_log.py`, `summarize_tegrastats.py` — analisis evidence pasca-uji.

### 2.5b `docs/` (root) dan `seano_ca_ws/docs/`

Catatan teknis/audit tambahan yang tidak masuk kategori runbook operasional
(mis. `PHASE7_ACTUATOR_INTERFACE_NOTES.md`, `audit_phase7_sync_policy.md`).
File yang Anda baca sekarang, beserta `RUNBOOK_POOL_EXISTING_CONTROL_PATH.md`
dan `CLEANUP_NOTES.md`, juga tinggal di `docs/` (root).

---

## 3. Fungsi file penting

| File | Peran |
|---|---|
| `event_logger_node.py` | Logger evaluasi/KTI. Menulis `events.csv/.jsonl`, `avoidance_cycles.csv`, `metrics_summary.csv/.json`, `time_series.csv` ke `~/seano_event_logs/<run_id>/`. Menyimpan frame HUD hanya jika `save_frames=true` (default **false**). Tidak memengaruhi jalur aktuasi — murni observer. |
| `risk_evaluator_node.py` | Inti evaluasi risiko: tracking objek, hitung risk score, tentukan mode lokal (`NORMAL`/`CAUTION`/`LOST_PERCEPTION`) dan usulan command (`/ca/command`, `/ca/risk`, `/ca/mode`). |
| `watchdog_failsafe_node.py` | Pantau kesehatan sinyal upstream (image/deteksi/vision quality). Jika stale/hilang → set `/ca/failsafe_active` dan latch command aman ke `/ca/command_safe`. |
| `command_mux_node.py` | Pilih sumber command aktif: MANUAL (`/seano/manual/*_cmd`) vs AUTO (`/seano/auto/*_cmd`), berdasarkan `/seano/auto_enable`. Bukan output final ke aktuator. |
| `actuator_safety_limiter_node.py` | "Pagar terakhir" sebelum bridge: terapkan failsafe, timeout input, clamp, dan slew-rate limiter atas output mux. Hasilnya `/seano/left_cmd`, `/seano/right_cmd`. |
| `mavros_rc_override_bridge_node.py` | Terjemahkan command left/right (atau throttle/rudder) menjadi `mavros_msgs/OverrideRCIn` dan publish ke `/mavros/rc/override`. **Ini satu-satunya node di repo ini yang bisa publish ke `/mavros/rc/override`.** |
| `phase7_cuav_usb_hardware.launch.py` | Launch file baseline hardware aktif (Jetson + CUAV + kamera USB). Semua script run di repo ini memanggil launch file ini dengan argumen berbeda-beda. |
| `run_pool_existing_control_path.sh` | **Script aktif untuk skema pengujian sekarang** (KTI, jalur kontrol eksisting). Preflight read-only lalu launch dengan `use_mavros:=false`, `use_rc_override_bridge:=false` — CA tidak menjalankan MAVROS/bridge sendiri, `/usv/thruster` rekan tetap satu-satunya publisher ke `/mavros/rc/override`. Lihat [RUNBOOK_POOL_EXISTING_CONTROL_PATH.md](RUNBOOK_POOL_EXISTING_CONTROL_PATH.md). |
| `run_phase7_monitor_no_log.sh` | Script run lama (baseline Phase 7 penuh: CA + bridge + evidence + tegrastats + pretty-live viewer). **Jangan dipakai untuk skema existing-control-path KTI** karena secara default menjalankan pipeline dengan asumsi bridge repo ini yang mengontrol aktuator, bukan `/usv/thruster` rekan. |
| `stop_phase7_safe.sh` | Stop helper untuk sesi yang dimulai oleh `run_phase7_monitor_no_log.sh` (baca `.last_phase7_run_dir`, matikan hanya proses milik sesi itu). Tidak dipakai oleh `run_pool_existing_control_path.sh` (yang cukup di-stop dengan Ctrl+C karena berjalan di foreground). |

---

## 4. Node aktif pada skema pool existing-control path

Untuk skema pool testing dengan jalur kontrol eksisting (`/usv/thruster`
rekan sebagai aktuator, dijalankan lewat
`seano_ca_ws/run_pool_existing_control_path.sh`), `ca_runtime_profile` yang
dipakai adalah default launch file, **`usb_watchdog`** — script ini tidak
mengoverride `ca_runtime_profile` sama sekali. Ini **bukan** profile `full`
(lihat §5).

Node yang benar-benar berjalan (dikonfirmasi lewat audit kode **dan** lewat
stdout run nyata di `/tmp/POOL_EXISTING_CONTROL_PATH_*_stdout.txt`):

- `camera_node.py` (atau `camera_hp` — node kamera, tergantung
  `ca_camera_launch`/profile kamera yang dipilih)
- `detector_node.py`
- `risk_evaluator_node.py`
- `watchdog_failsafe_node.py`
- `command_mux_node.py`
- `actuator_safety_limiter_node.py`
- `auto_controller_stub_node.py`
- `mission_mode_manager_node.py`
- `event_logger_node.py`

**`mavros_rc_override_bridge_node.py` sengaja tidak dijalankan** pada skema
ini (`use_rc_override_bridge:=false`), supaya `/usv/thruster` rekan tetap
satu-satunya publisher ke `/mavros/rc/override`. MAVROS baru juga tidak
dijalankan (`use_mavros:=false`).

**Mekanisme LOST_PERCEPTION / failsafe kualitas kamera pada skema aktif ini
berasal dari `risk_evaluator_node.py` (vision-quality dihitung internal di
dalam node itu sendiri dari frame gambar, parameter
`use_internal_vision_quality=True`) dan `watchdog_failsafe_node.py` (staleness
check atas image/risk/mode) — BUKAN dari node `vision_quality_node.py`
eksternal**, karena node itu tidak berjalan pada profile `usb_watchdog` (lihat
§5). Temuan ini dikonfirmasi lewat log run nyata: event `ca_mode=LOST_PERCEPTION`
tercatat dengan `reason_codes=LOST_PERCEPTION;FORCED_STOP`, yang di-set
langsung oleh `risk_evaluator_node.py`, bukan oleh node terpisah.

Selain node di atas: `models/yolov8n.pt` / `.onnx` / `.engine` (model deteksi
aktif).

Detail prosedur ada di [RUNBOOK_POOL_EXISTING_CONTROL_PATH.md](RUNBOOK_POOL_EXISTING_CONTROL_PATH.md).

## 5. Node optional profile `full`

Lima node berikut **terdaftar sebagai executable resmi** (lihat
`seano_ca_ws/src/seano_vision/setup.py`) dan **dipanggil secara sah** di
`seano_ca_ws/src/seano_vision/launch/demo_full_ca.launch.py` — ini bukan kode
sampah/orphan, hanya tidak aktif pada profile pengujian sekarang:

| Node | Fungsi (kalau aktif) |
|---|---|
| `vision_quality_node.py` | Skor kualitas gambar eksternal (blur, gelap, dsb) → `/vision/quality` |
| `false_positive_guard_node.py` | Filter false-positive deteksi (temporal N-of-M + opsional waterline check) → `/camera/detections_filtered` |
| `frame_freeze_detector_node.py` | Deteksi kamera beku/hang (hash-repeat) → `/vision/freeze` |
| `multi_target_fusion_node.py` | Fusi/ranking multi-objek terdeteksi → `/camera/detections_fused` |
| `waterline_horizon_node.py` | Estimasi garis air/horizon untuk ROI maritim → `/vision/waterline_y` |

**Kelima node ini hanya aktif jika `ca_runtime_profile:=full`** dipassing
eksplisit saat launch (atau argumen `use_vq` / `use_fp_guard` /
`use_freeze` / `use_fusion` / `use_waterline` diaktifkan manual satu-satu
lewat launch opsional `demo_full_ca.launch.py`). Pada
`phase7_cuav_usb_hardware.launch.py`, argumen turunannya (`ca_use_vq`,
`ca_use_fp_guard`, `ca_use_freeze`, `ca_use_fusion`, `ca_use_waterline`)
semuanya default `false` kecuali profile `full` dipilih.

**Pada skema `run_pool_existing_control_path.sh`, kelima node ini TIDAK
aktif** — script itu memakai profile `usb_watchdog`, bukan `full` (lihat §4).

> **Peringatan: jangan hapus kelima file ini.** Mereka mendukung profile
> `full` dan mode perception/safety opsional (fusion multi-target, filter
> false-positive berbasis waterline, deteksi freeze eksternal, vision quality
> eksternal). Ini bukan node yang "ditinggalkan" — statusnya optional by
> design, dipakai kalau operator sengaja memilih profile `full` untuk
> pengujian dengan pipeline persepsi lebih lengkap.

## 6. Jangan disentuh tanpa alasan kuat

- **Source node Python** (`seano_ca_ws/src/seano_vision/seano_vision/*.py`) —
  safety-critical, perubahan harus melalui review dan konteks dari
  `AGENTS.md`/`PRD.md`.
- **Lima node optional profile `full`** (`vision_quality_node.py`,
  `false_positive_guard_node.py`, `frame_freeze_detector_node.py`,
  `multi_target_fusion_node.py`, `waterline_horizon_node.py`) — jangan hapus
  hanya karena tidak aktif di profile `usb_watchdog`/skema pengujian sekarang;
  lihat §5.
- **Launch file** (`seano_ca_ws/src/seano_vision/launch/*.py`) — parameter
  ikut safety-critical (channel PWM, timeout, dsb).
- **`run_phase7_monitor_no_log.sh`, `stop_phase7_safe.sh`** — dipakai untuk
  skema pengujian lama yang masih valid untuk kasus non-existing-control-path;
  jangan diedit hanya demi skema pool testing baru — buat script baru seperti
  `run_pool_existing_control_path.sh`.
- **`models/yolov8n.pt`, `.onnx`, `.engine`** — `.pt` adalah source model
  (tracked git), `.onnx`/`.engine` adalah hasil build TensorRT aktif yang
  dipakai runtime Jetson; menghapusnya berarti perlu export ulang yang lambat.
- **`.last_phase7_run_dir`, `.phase7_runtime/`** — state runtime yang dipakai
  `run_phase7_monitor_no_log.sh` / `stop_phase7_safe.sh` untuk melacak sesi
  aktif.
- **`PRD.md`, `AGENTS.md`, `SKILLS.md`, `README.md`, `package.xml`,
  `setup.py`, `setup.cfg`, `requirements.txt`, `.gitignore`** — dokumentasi
  dan metadata paket inti.
