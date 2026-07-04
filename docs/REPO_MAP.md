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
Alur singkatnya (detail lengkap ada di `seano_ca_ws/README.md` §2–§3):

```
kamera → detector_node → false_positive_guard_node → risk_evaluator_node
  → watchdog_failsafe_node → command_mux_node → actuator_safety_limiter_node
  → mavros_rc_override_bridge_node → FCU (MAVROS) → aktuator
```

`event_logger_node.py` dan `mission_mode_manager_node.py` mengamati/mengatur
state di sekeliling alur di atas, bukan bagian dari jalur data utama.

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

## 4. Mana yang aktif untuk skema pengujian sekarang

Untuk skema pool testing dengan jalur kontrol eksisting (`/usv/thruster`
rekan sebagai aktuator), yang dipakai adalah:

- `seano_ca_ws/run_pool_existing_control_path.sh` (entry point)
- `seano_ca_ws/src/seano_vision/launch/phase7_cuav_usb_hardware.launch.py` (dipanggil oleh script di atas)
- Semua node di `seano_ca_ws/src/seano_vision/seano_vision/` **kecuali** `mavros_rc_override_bridge_node.py` (sengaja tidak dijalankan — lihat argumen `use_rc_override_bridge:=false`)
- `models/yolov8n.pt` / `.onnx` / `.engine` (model deteksi aktif)
- `event_logger_node.py` untuk logging KTI ke `~/seano_event_logs/`

Detail prosedur ada di [RUNBOOK_POOL_EXISTING_CONTROL_PATH.md](RUNBOOK_POOL_EXISTING_CONTROL_PATH.md).

## 5. Jangan disentuh tanpa alasan kuat

- **Source node Python** (`seano_ca_ws/src/seano_vision/seano_vision/*.py`) —
  safety-critical, perubahan harus melalui review dan konteks dari
  `AGENTS.md`/`PRD.md`.
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
